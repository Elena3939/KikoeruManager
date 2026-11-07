"""社团字幕入口；只解析索引位置，复用已有字幕爬取。"""
import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import or_, text
from ..models.database import CircleSubtitleTargetSnapshot, CircleWork, LibraryIndexStatus, ResourceSourceProbe, SessionLocal, Task as TaskRecord, WorkCanonicalLink, WorkMetadata
from .rj_subtitle_task_service import existing_location_task, location_key, submit_subtitle_task, subtitle_creation_guard, task_payload

logger = logging.getLogger(__name__)
PROBE_SOURCE = 'rj_subtitle'
PROBE_VERSION = 1


class SubtitleRepairTargetSkipped(ValueError):
    """目标状态已变化，停止抓取但不误报补配成功。"""


def normalize_code(value):
    value = str(value or '').strip().upper()
    return value if re.fullmatch(r'RJ(?:\d{6}|\d{8})', value) else ''


def source_evidence(payload):
    from .yaas_subtitle_service import cached_archive_files
    source = payload.get('selected_source') or {}
    if not payload.get('has_subtitle'):
        return []
    evidence = {'kind': 'subtitle' if payload.get('subtitle_verified') else 'subtitle_package',
             'label': '发现字幕' if payload.get('subtitle_verified') else '发现字幕包',
             'rjcode': source.get('rjcode', ''), 'provider': source.get('source_provider', ''),
             'is_ai': bool(source.get('subtitle_is_ai')), 'lang': source.get('lang', ''),
             'work_type': source.get('work_type', '')}
    if source.get('source_provider') == 'yaas':
        files = cached_archive_files(source)
        if files:
            evidence.update(archive_files=files, subtitle_package=source.get('subtitle_package', True))
    return [evidence]


def translation_resource_evidence(translated, asmr_code, yaas_codes):
    hits = set(translated).intersection(yaas_codes)
    if asmr_code in translated:
        hits.add(asmr_code)
    return [{'kind': 'translated_audio', 'label': '关联中文资源，待爬取验证',
             'rjcode': code, 'provider': 'resource_probe'} for code in sorted(hits)]


class CircleSubtitleRepairService:
    def target_index_version(self, db):
        from .library_manager import get_library_manager
        libraries = sorted(get_library_manager()._active_libraries(), key=lambda item: item.id)
        statuses = {row.library_id: row for row in db.query(LibraryIndexStatus).populate_existing().all()}
        parts, ready = [], True
        for library in libraries:
            status = statuses.get(library.id)
            parts.append([
                library.id, library.type, library.browse_root_path, library.root_path,
                library.writable,
                status.active_generation if status else None,
            ])
            if not status or status.status not in ('ready', 'syncing') or int(status.accepted_seq or 0) != int(status.materialized_seq or 0):
                ready = False
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest(), ready

    def refresh_target_snapshots(self):
        """后台分批回填；版本变化时旧结果不会被当作当前状态。"""
        from sqlalchemy.dialects.postgresql import insert
        from .circle_completion_service import get_circle_completion_service
        from .realtime_event_service import broadcast_event
        with SessionLocal() as db:
            if not db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {'key': 6172451843072}).scalar():
                return
            pending = db.query(CircleSubtitleTargetSnapshot).filter(
                CircleSubtitleTargetSnapshot.notified.is_(False)).order_by(
                    CircleSubtitleTargetSnapshot.rjcode).limit(100).with_for_update().all()
            if pending:
                codes = [row.rjcode for row in pending]
                circles = db.query(CircleWork.circle_id).filter(
                    CircleWork.canonical_rjcode.in_(codes)).distinct().all()
                service = get_circle_completion_service()
                for (circle_id,) in circles:
                    version = service.invalidate_completion_resource_cache(circle_id)
                    broadcast_event({'type': 'circle.resource_source.changed', 'domain': 'circle_completion',
                                     'payload': {'circle_id': circle_id, 'source': 'subtitle_targets',
                                                 'rjcodes': codes, 'version': version}})
                for row in pending:
                    row.notified = True
                db.commit()
                return True
            version, ready = self.target_index_version(db)
            if not ready:
                return
            rows = db.query(CircleWork.canonical_rjcode).outerjoin(
                CircleSubtitleTargetSnapshot,
                CircleSubtitleTargetSnapshot.rjcode == CircleWork.canonical_rjcode,
            ).filter(CircleWork.is_bonus_work.is_(False),
                     CircleWork.canonical_rjcode.isnot(None),
                     CircleWork.canonical_rjcode.op('~')(r'^RJ([0-9]{6}|[0-9]{8})$'),
                     or_(CircleSubtitleTargetSnapshot.rjcode.is_(None),
                         CircleSubtitleTargetSnapshot.index_version != version)).distinct().order_by(
                             CircleWork.canonical_rjcode).limit(100).all()
            codes = [code for (code,) in rows if normalize_code(code) == code]
            if not codes:
                return
            placeholders = [dict(rjcode=code, index_version='', target_count=0,
                missing_count=0, complete=False, notified=True, updated_at=datetime.now()) for code in codes]
            db.execute(insert(CircleSubtitleTargetSnapshot).values(placeholders).on_conflict_do_nothing())
            locked = db.query(CircleSubtitleTargetSnapshot).filter(
                CircleSubtitleTargetSnapshot.rjcode.in_(codes)).order_by(
                    CircleSubtitleTargetSnapshot.rjcode).with_for_update().all()
            codes = [row.rjcode for row in locked if row.index_version != version]
            if not codes:
                db.commit()
                return True
            targets = self.indexed_targets(codes)
            current, still_ready = self.target_index_version(db)
            if current != version or not still_ready:
                return
            values = []
            for code in codes:
                locations = targets.get(code, [])
                values.append(dict(rjcode=code, index_version=version, target_count=len(locations),
                    missing_count=sum(bool(item['eligible']) for item in locations),
                    complete=all(item.get('index_complete', False) for item in locations),
                    notified=False, updated_at=datetime.now()))
            stmt = insert(CircleSubtitleTargetSnapshot).values(values)
            db.execute(stmt.on_conflict_do_update(index_elements=['rjcode'], set_={
                key: getattr(stmt.excluded, key) for key in (
                    'index_version', 'target_count', 'missing_count', 'complete', 'notified', 'updated_at')
            }))
            db.commit()
            return True

    @staticmethod
    def validate_path(library, path):
        from .library_manager import get_library_manager
        manager = get_library_manager()
        if library.type == 'synology_filestation':
            normalized = manager._normalize_remote_path(path)
            root = manager._normalize_remote_path(library.browse_root_path or library.root_path or '/')
            valid = '..' not in PurePosixPath(path).parts and manager._remote_path_is_within_root(normalized, root)
        else:
            valid = manager._local_path_is_within_root(str(Path(path).resolve()), str(Path(library.browse_root_path or library.root_path).resolve()))
        if not valid:
            raise PermissionError('目标不在库存范围内')
        if library.writable is False:
            raise PermissionError('库存只读')

    def indexed_targets(self, codes):
        from .library_index import get_library_index_service
        from .library_manager import get_library_manager
        from .rj_subtitle_service import get_rj_subtitle_service
        from .request_performance import measure_stage, request_metrics
        manager, index, subtitle = get_library_manager(), get_library_index_service(), get_rj_subtitle_service()
        result = {code: [] for code in codes}
        libraries = {lib.id: lib for lib in manager._active_libraries() if index.has_usable_snapshot(lib.id)}
        metrics = request_metrics.get()
        if metrics is not None:
            metrics['subtitle_library_count'] = len(libraries)
            metrics['subtitle_directory_count'] = 0
        if not libraries or not codes:
            return result
        with measure_stage('subtitle_directory_query_ms'):
            entries = index.find_by_rjcodes(list(codes), list(libraries), entry_type='dir', limit=10001)
        if len(entries) >= 10001:
            raise ValueError('原作位置过多，请缩小选中作品范围')
        # 索引的子目录也可能继承 RJ，只统计名称明确属于原作的作品根目录。
        entries = [entry for entry in entries if {c.upper() for c in re.findall(
            r'RJ(?:\d{8}|\d{6})(?!\d)', entry.name or '', re.I)} == {normalize_code(entry.rjcode)}]
        if metrics is not None:
            metrics['subtitle_directory_count'] = len(entries)
        summaries = {}
        for library_id in libraries:
            paths = [entry.relative_path for entry in entries if entry.library_id == library_id]
            if paths:
                with measure_stage('subtitle_directory_summary_ms'):
                    summaries[library_id] = index.summarize_subtitle_targets_many(library_id, paths,
                        audio_extensions=subtitle.AUDIO_EXTENSIONS, subtitle_extensions=subtitle.SUBTITLE_EXTENSIONS)
        seen = set()
        for entry in entries:
            code, library = normalize_code(entry.rjcode), libraries.get(entry.library_id)
            if code not in result or not library:
                continue
            path = str(entry.absolute_path or '')
            try:
                self.validate_path(library, path)
            except (ValueError, PermissionError):
                continue
            key = location_key(library.id, path)
            if key in seen:
                continue
            seen.add(key)
            summary = summaries.get(library.id, {}).get(entry.relative_path)
            complete = summary is not None
            audio = (summary or {}).get('audio_count', 0)
            count = (summary or {}).get('subtitle_count', 0)
            result[code].append({'rjcode': code, 'library_id': library.id, 'library_name': library.name,
                'library_type': library.type, 'folder_path': path, 'folder_name': entry.name,
                'subtitle_count': count, 'audio_count': audio, 'index_complete': complete,
                'eligible': complete and not count and audio > 0,
                'reason': '目录摘要超出检查上限' if not complete else '已有字幕' if count else '无音频' if not audio else ''})
        return result

    def decorate_items(self, db, items):
        from .request_performance import measure_stage, request_metrics
        codes = {normalize_code(item.get('canonical_rjcode')) for item in items if not item.get('is_bonus_work') and not item.get('is_unreleased')} - {''}
        metrics = request_metrics.get()
        if metrics is not None:
            metrics['subtitle_work_count'] = len(codes)
        version, ready = self.target_index_version(db)
        targets = {row.rjcode: row for row in db.query(CircleSubtitleTargetSnapshot).filter(
            CircleSubtitleTargetSnapshot.rjcode.in_(codes),
            CircleSubtitleTargetSnapshot.index_version == version).all()} if codes and ready else {}
        with measure_stage('subtitle_probe_query_ms'):
            probes = {row.rjcode: row for row in db.query(ResourceSourceProbe).filter(
                ResourceSourceProbe.source == PROBE_SOURCE, ResourceSourceProbe.probe_version == PROBE_VERSION,
                ResourceSourceProbe.rjcode.in_(codes)).all()} if codes else {}
        for item in items:
            code = normalize_code(item.get('canonical_rjcode'))
            target = targets.get(code) if not item.get('is_bonus_work') and not item.get('is_unreleased') else None
            probe = probes.get(code)
            evidence = list(probe.candidates or []) if probe and probe.status == 'hit' else []
            translated = set(item.get('subtitle_translation_rjcodes') or [])
            yaas = next((s for s in item.get('resource_sources', []) if s.get('id') == 'imoutoheaven'), {})
            evidence += translation_resource_evidence(translated, item.get('asmr_available_rjcode') if item.get('has_asmr_one') else '', yaas.get('rjcodes') or [])
            item.update(subtitle_repairable=bool(target and target.complete and target.missing_count and evidence),
                subtitle_repair_sources=evidence,
                subtitle_original_target_count=target.target_count if target else 0,
                subtitle_missing_target_count=target.missing_count if target else 0,
                subtitle_target_status=('ready' if target.complete else 'incomplete') if target else
                    ('pending' if code in codes else 'not_applicable'),
                subtitle_repair_probe_status=probe.status if probe else 'pending')

    def enqueue_probe_codes(self, codes, *, refresh=False):
        from sqlalchemy.dialects.postgresql import insert
        normalized = list(dict.fromkeys(filter(None, (normalize_code(code) for code in codes))))
        if not normalized:
            return 0
        now = datetime.now()
        values = [dict(source=PROBE_SOURCE, rjcode=code, probe_version=PROBE_VERSION,
                       status='pending', candidates=[], error='', expires_at=now if refresh else None)
                  for code in normalized]
        with SessionLocal() as db:
            for offset in range(0, len(values), 500):
                statement = insert(ResourceSourceProbe).values(values[offset:offset + 500])
                db.execute(statement.on_conflict_do_nothing())
                if refresh:
                    db.query(ResourceSourceProbe).filter(
                        ResourceSourceProbe.source == PROBE_SOURCE,
                        ResourceSourceProbe.probe_version == PROBE_VERSION,
                        ResourceSourceProbe.rjcode.in_(normalized[offset:offset + 500]),
                    ).update({ResourceSourceProbe.status: 'pending', ResourceSourceProbe.expires_at: now}, synchronize_session=False)
            db.commit()
        return len(normalized)

    def enqueue_circle_probe(self, circle_id, *, refresh=False):
        with SessionLocal() as db:
            codes = [row[0] for row in db.query(CircleWork.canonical_rjcode).filter(
                CircleWork.circle_id == circle_id,
                CircleWork.is_bonus_work.is_(False),
            ).distinct().all()]
        return self.enqueue_probe_codes(codes, refresh=refresh)

    async def probe_pending(self):
        from .resource_source_service import get_resource_source_service
        def pending():
            with SessionLocal() as db:
                return [row.rjcode for row in db.query(ResourceSourceProbe).filter(
                    ResourceSourceProbe.source == PROBE_SOURCE, ResourceSourceProbe.probe_version == PROBE_VERSION,
                    ResourceSourceProbe.status == 'pending',
                ).order_by(ResourceSourceProbe.checked_at.asc().nullsfirst()).limit(2).all()]
        resource = get_resource_source_service()
        for code in await asyncio.to_thread(pending):
            async with resource.lease('subtitle-probe-' + code):
                with SessionLocal() as db:
                    row = db.get(ResourceSourceProbe, (PROBE_SOURCE, code, PROBE_VERSION))
                    fresh = row is None or row.status != 'pending'
                if not fresh:
                    await self._probe_code(code)

    async def _probe_code(self, code):
        from .rj_subtitle_service import get_rj_subtitle_service
        from .resource_source_service import get_resource_source_service
        status, evidence, error = 'error', [], '字幕来源暂不可用，请稍后重试'
        try:
            service = get_rj_subtitle_service()
            payload = await service.probe_cached_subtitle_availability(code)
            evidence = source_evidence(payload)
            status = 'hit' if evidence else 'missing' if service._can_cache_subtitle_absence(payload.get('attempts') or []) else 'unknown'
            if status in {'hit', 'missing'}:
                error = ''
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning('社团字幕来源探测失败 rj=%s', code, exc_info=True)
        def save():
            with SessionLocal() as db:
                row = db.get(ResourceSourceProbe, (PROBE_SOURCE, code, PROBE_VERSION))
                if row is None:
                    return
                changed = (row.status, row.candidates) != (status, evidence)
                row.status, row.candidates, row.error = status, evidence, error
                row.checked_at = datetime.now()
                row.expires_at = None
                db.commit()
            if changed:
                get_resource_source_service().notify_circles(code)
        await asyncio.to_thread(save)

    def resolve_targets(self, circle_id, codes):
        codes = list(dict.fromkeys(normalize_code(code) for code in codes))
        if not codes or '' in codes or len(codes) > 100:
            raise ValueError('每次请选择 1 至 100 个有效原作 RJ')
        with SessionLocal() as db:
            rows = db.query(CircleWork).filter(CircleWork.circle_id == circle_id, CircleWork.canonical_rjcode.in_(codes)).all()
            from .release_dates import is_unreleased
            unreleased = {row.rjcode for row in db.query(WorkMetadata).filter(WorkMetadata.rjcode.in_(codes)).all() if is_unreleased(row.release_date)}
            valid = {row.canonical_rjcode for row in rows if not row.is_bonus_work and row.canonical_rjcode not in unreleased}
        targets = self.indexed_targets(valid)
        return [{'canonical_rjcode': code, 'targets': targets.get(code, []),
                 'reason': '作品不属于当前社团或不是原作' if code not in valid else '库存索引未找到真实原作目录，请刷新索引' if not targets.get(code) else ''} for code in codes]

    def translation_hints(self, db, circle_id, code):
        from .resource_source_service import SOURCE, VERSION
        from .circle_completion_service import get_circle_completion_service
        completion = get_circle_completion_service()
        translated = {row.linked_rjcode: row for row in db.query(WorkCanonicalLink).filter(
            WorkCanonicalLink.canonical_rjcode == code,
        ).all() if completion._variant_group(row.link_type, row.lang)['key'] in {'simplified', 'traditional'}}
        row = db.query(CircleWork).filter(CircleWork.circle_id == circle_id, CircleWork.canonical_rjcode == code, CircleWork.is_bonus_work.is_(False)).first()
        yaas_codes = {probe.rjcode for probe in db.query(ResourceSourceProbe).filter(
            ResourceSourceProbe.source == SOURCE, ResourceSourceProbe.probe_version == VERSION,
            ResourceSourceProbe.rjcode.in_(translated), ResourceSourceProbe.status == 'hit',
        ).filter(ResourceSourceProbe.candidates.contains([{'complete': True}])).all()} if translated else set()
        asmr_code = row.asmr_available_rjcode if row and row.has_asmr_one else ''
        return [dict(rjcode=code, provider=provider, kind='translated_audio',
                     lang=translated[code].lang, work_type=translated[code].link_type)
                for provider, codes in [('asmr.one', [asmr_code] if asmr_code in translated else []),
                                        ('yaas', sorted(yaas_codes))]
                for code in codes]

    def has_source(self, circle_id, code):
        return bool(self.source_hint(code, circle_id))

    def source_hint(self, code, circle_id=None):
        with SessionLocal() as db:
            probe = db.get(ResourceSourceProbe, (PROBE_SOURCE, code, PROBE_VERSION))
            for candidate in (probe.candidates or []) if probe and probe.status == 'hit' else []:
                rjcode = normalize_code(candidate.get('rjcode'))
                provider = str(candidate.get('provider') or '').strip().lower()
                if rjcode and provider in {'asmr.one', 'yaas'}:
                    hint = {
                        'rjcode': rjcode,
                        'provider': provider,
                        'is_ai': bool(candidate.get('is_ai')),
                        'lang': str(candidate.get('lang') or ''),
                        'work_type': str(candidate.get('work_type') or ''),
                    }
                    if not hint['lang'] or not hint['work_type']:
                        link = db.query(WorkCanonicalLink).filter(
                            WorkCanonicalLink.canonical_rjcode == code,
                            WorkCanonicalLink.linked_rjcode == rjcode,
                        ).first()
                        # 兼容旧探测摘要，使用持久化关联补齐语言，不重新请求源站。
                        hint['lang'] = hint['lang'] or (link.lang if link else '') or ('JPN' if rjcode == code else '')
                        hint['work_type'] = hint['work_type'] or (link.link_type if link else '') or ('original' if rjcode == code else '')
                    if provider == 'yaas' and candidate.get('archive_files'):
                        from .yaas_subtitle_service import cached_archive_files
                        files = cached_archive_files(candidate)
                        if files:
                            hint.update(archive_files=files, subtitle_package=candidate.get('subtitle_package', True))
                    return hint
            if circle_id:
                hints = self.translation_hints(db, circle_id, code)
                if hints:
                    return {**hints[0], 'fallback_hints': hints[1:]}
        return None

    def task_states(self, circle_id, codes):
        from .task_engine import get_task_engine
        engine = get_task_engine()
        with SessionLocal() as db:
            works = db.query(
                CircleWork.canonical_rjcode,
                CircleWork.display_rjcode,
                CircleWork.linked_rjcodes,
                CircleWork.asmr_available_rjcode,
            ).filter(
                CircleWork.circle_id == circle_id,
                CircleWork.canonical_rjcode.in_(codes),
                CircleWork.is_bonus_work.is_(False),
            ).all()
            canonical_by_code = {}
            valid = set()
            for work in works:
                canonical = str(work.canonical_rjcode or "").upper()
                if not canonical:
                    continue
                valid.add(canonical)
                for code in [
                    canonical,
                    work.display_rjcode,
                    work.asmr_available_rjcode,
                    *(work.linked_rjcodes or []),
                ]:
                    normalized = str(code or "").upper()
                    if normalized:
                        canonical_by_code[normalized] = canonical
            task_codes = set(canonical_by_code)
            rows = db.query(TaskRecord).filter(TaskRecord.type == 'rj_subtitle_fetch',
                or_(TaskRecord.task_metadata['rjcode'].as_string().in_(task_codes),
                    TaskRecord.task_metadata['actual_rjcode'].as_string().in_(task_codes),
                    TaskRecord.task_metadata['circle_canonical_rjcode'].as_string().in_(valid)),
            ).order_by(TaskRecord.created_at.desc()).all()
        result, seen = {code: [] for code in codes}, set()
        tasks = {row.id: engine.tasks.get(row.id) or row for row in rows}
        ordered = sorted(tasks.values(), key=lambda task: (
            getattr(task.status, 'value', task.status) in {'pending', 'processing', 'paused', 'waiting_manual', 'waiting_retry'}
            or task_payload(task)['awaiting_manual_match'], task.created_at or datetime.min), reverse=True)
        for task in ordered:
            payload = task_payload(task)
            key = location_key(payload['library_id'], payload['folder_path'])
            if key in seen:
                continue
            metadata = task.task_metadata or {}
            code = str(metadata.get('circle_canonical_rjcode') or "").upper()
            if code not in result:
                code = canonical_by_code.get(
                    str(metadata.get('actual_rjcode') or metadata.get('rjcode') or "").upper(),
                    "",
                )
            if code in result:
                seen.add(key)
                result[code].append(payload)
        return result

    async def inspect_target(self, target):
        from .library_manager import get_library_manager
        from .rj_subtitle_service import get_rj_subtitle_service
        library = get_library_manager().get_library_definition(target['library_id'])
        self.validate_path(library, target['folder_path'])
        subtitle = get_rj_subtitle_service()
        if library.type == 'synology_filestation':
            manager = get_library_manager()
            client = manager.get_cached_synology_client(library.synology)
            info = manager._first_remote_info_item(await client.stat(target['folder_path']))
            if not info or not info.get('isdir'):
                raise FileNotFoundError('原作目录已不存在')
            if normalize_code(subtitle.extract_rjcode(PurePosixPath(target['folder_path']).name)) != target['rjcode']:
                raise ValueError('原作目录失效或 RJ 不匹配')
            contents = await manager.folder_contents(library.id, target['folder_path'], client=client, prefer_index=False)
            entries = contents.get('items') or []
            state = {'audio_count': len(subtitle._collect_remote_audio_entries(entries)),
                'existing_subtitle_count': sum(Path(item.get('name') or '').suffix.lower() in subtitle.SUBTITLE_EXTENSIONS for item in entries if not item.get('is_dir') and not item.get('isdir'))}
        else:
            if not Path(target['folder_path']).is_dir():
                raise FileNotFoundError('原作目录已不存在')
            if normalize_code(subtitle.extract_rjcode(Path(target['folder_path']).name)) != target['rjcode']:
                raise ValueError('原作目录失效或 RJ 不匹配')
            state = await asyncio.to_thread(subtitle._build_local_scan_result, Path(target['folder_path']))
            def count_subtitles():
                count = 0
                def fail(exc):
                    raise exc
                for root, dirs, files in os.walk(target['folder_path'], onerror=fail, followlinks=False):
                    dirs[:] = [name for name in dirs if not Path(root, name).is_symlink()]
                    count += sum(Path(name).suffix.lower() in subtitle.SUBTITLE_EXTENSIONS for name in files)
                return count
            state['existing_subtitle_count'] = await asyncio.to_thread(count_subtitles)
        if state.get('existing_subtitle_count', 0):
            raise SubtitleRepairTargetSkipped('所选目录已有字幕')
        if not state.get('audio_count'):
            raise SubtitleRepairTargetSkipped('所选目录没有音频')
        return state

    async def start(self, circle_id, codes, selections=None):
        from .task_engine import get_task_engine
        from ..config.settings import get_config
        groups = await asyncio.to_thread(self.resolve_targets, circle_id, codes)
        engine, config = get_task_engine(), get_config()
        results = []
        for group in groups:
            code, targets = group['canonical_rjcode'], group['targets']
            if not targets:
                results.append({'canonical_rjcode': code, 'state': 'skipped', 'reason': group['reason']})
                continue
            requested = (selections or {}).get(code)
            if len(targets) > 1 and requested is None:
                results.append({**group, 'state': 'selection_required'})
                continue
            selected = {location_key(t.get('library_id'), t.get('folder_path')) for t in requested} if requested is not None else {location_key(targets[0]['library_id'], targets[0]['folder_path'])}
            if not selected:
                results.append({'canonical_rjcode': code, 'state': 'skipped', 'reason': '未选择库存位置'})
            available = {location_key(t['library_id'], t['folder_path']): t for t in targets}
            for key in selected:
                target = available.get(key)
                if target is None:
                    results.append({'canonical_rjcode': code, 'state': 'skipped', 'reason': '选中位置已变化或不属于当前原作'})
                    continue
                try:
                    async with subtitle_creation_guard(target['library_id'], target['folder_path']) as db:
                        existing = await asyncio.to_thread(existing_location_task, engine, target['library_id'], target['folder_path'], db=db, include_failed=True)
                        if existing:
                            results.append({'canonical_rjcode': code, 'state': 'reused', **existing})
                            continue
                        if not target['eligible']:
                            raise ValueError(target['reason'])
                        source_hint = await asyncio.to_thread(self.source_hint, code, circle_id)
                        if not source_hint:
                            raise ValueError('尚未探测到可用字幕或关联中文资源，请等待资源探测')
                        await self.inspect_target(target)
                        metadata = {**config.rj_subtitle.model_dump(), 'overwrite': False, 'force_rerun': False,
                            'skip_if_existing_subtitles': True, 'existing_subtitle_scope': 'folder', 'subtitle_index_query_mode': 'exact',
                            'folder_path': target['folder_path'], 'folder_name': target['folder_name'], 'library_id': target['library_id'], 'rjcode': code,
                            'ai_match_mode': config.ai_subtitle_matching.default_mode, 'ai_confidence_threshold': config.ai_subtitle_matching.confidence_threshold,
                            'task_domain': 'rj_subtitle', 'source_page': 'circle-completion', 'source_label': f'社团字幕补配 · {code}',
                            'source_action': 'circle_subtitle_repair', 'circle_id': circle_id, 'circle_canonical_rjcode': code}
                        if source_hint:
                            metadata['subtitle_source_hint'] = source_hint
                        task = await submit_subtitle_task(engine, folder_path=target['folder_path'], metadata=metadata)
                        results.append({'canonical_rjcode': code, 'state': 'created', **task_payload(task)})
                except (ValueError, PermissionError, FileNotFoundError) as exc:
                    results.append({**target, 'canonical_rjcode': code, 'state': 'skipped', 'reason': str(exc)})
                except Exception:
                    logger.exception('社团字幕任务创建失败 rj=%s', code)
                    results.append({**target, 'canonical_rjcode': code, 'state': 'skipped', 'reason': '目录检查或任务创建失败，请重试'})
        return {'success': True, 'items': results, 'created_count': sum(r['state'] == 'created' for r in results),
                'reused_count': sum(r['state'] == 'reused' for r in results), 'skipped_count': sum(r['state'] == 'skipped' for r in results)}


_service = CircleSubtitleRepairService()


def get_circle_subtitle_repair_service():
    return _service
