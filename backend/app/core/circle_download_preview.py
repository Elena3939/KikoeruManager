"""社团下载的语言发现与精确版本计划。归组编号不代表下载目标。"""
import asyncio
import os
import re
from copy import deepcopy

from ..models.database import CircleCatalog, CircleWork


class CircleDownloadPreviewMixin:
    def _download_rjcode(self, value):
        """预览链路只接受可解析成完整 RJ 编号的值，拒绝把原始脏文本落库。"""
        normalized = self.normalize_rjcode(value)
        return normalized if re.fullmatch(r"[RVB]J(?:\d{6}|\d{8})", normalized) else ""

    def _unreleased_download_codes(self, codes):
        from .circle_completion_service import SessionLocal
        from ..models.database import WorkMetadata
        from .release_dates import is_unreleased

        with SessionLocal() as db:
            return {row.rjcode for row in db.query(WorkMetadata).filter(
                WorkMetadata.rjcode.in_(codes)).all() if is_unreleased(row.release_date)}

    def _sync_download_version_links(self, context, links):
        """预览发现的已验证语言链同步到社团索引，不改变作品归组身份。"""
        from uuid import uuid4
        from datetime import datetime
        from sqlalchemy.dialects.postgresql import insert
        from .circle_completion_service import SessionLocal
        from ..models.database import WorkCanonicalLink

        canonical = self._download_rjcode(context.get('canonical_rjcode'))
        if not canonical:
            return
        valid_links = []
        for item in links:
            code = self._download_rjcode(item.get('rjcode'))
            if code and item.get('work_type') in {'original', 'translation', 'child_translation'}:
                valid_links.append({**item, 'rjcode': code})
        codes = list(dict.fromkeys([canonical, *[item['rjcode'] for item in valid_links]]))
        with SessionLocal() as db:
            affected = db.query(CircleWork).filter(
                CircleWork.canonical_rjcode == canonical,
                CircleWork.is_bonus_work.isnot(True)).all()
            for item in valid_links:
                statement = insert(WorkCanonicalLink).values(
                    id=str(uuid4()), canonical_rjcode=canonical, linked_rjcode=item['rjcode'],
                    link_type=item['work_type'], lang=item.get('lang') or '',
                    evidence_source=item.get('evidence_source') or 'dlsite',
                    evidence_status='verified', cached_at=datetime.now())
                db.execute(statement.on_conflict_do_update(
                    index_elements=['canonical_rjcode', 'linked_rjcode'],
                    set_={field: getattr(statement.excluded, field) for field in (
                        'link_type', 'lang', 'evidence_source', 'evidence_status', 'cached_at')}))
            for row in affected:
                row.linked_rjcodes = list(dict.fromkeys([*(row.linked_rjcodes or []), *codes]))
            affected_circles = {row.circle_id for row in affected}
            db.commit()
        for code in codes:
            self._canonical_cache.pop(code, None)
        for circle_id in affected_circles:
            self.invalidate_completion_view_cache(circle_id)

    def _download_preview_context(self, circle_id, canonical):
        from .circle_completion_service import SessionLocal
        canonical = self._download_rjcode(canonical)
        if not canonical:
            raise ValueError("作品 RJ 编号无效")
        with SessionLocal() as db:
            catalog = db.query(CircleCatalog).filter_by(circle_id=circle_id).first()
            row = db.query(CircleWork).filter_by(circle_id=circle_id, canonical_rjcode=canonical).first()
            if catalog is None or row is None:
                raise ValueError("社团作品不存在")
            return dict(circle_id=circle_id, circle_name=catalog.circle_name,
                        canonical_rjcode=canonical, display_rjcode=canonical if row.is_bonus_work else row.display_rjcode or canonical,
                        title=row.title, is_bonus_work=bool(row.is_bonus_work))

    def _download_preview_limiter(self):
        if not hasattr(self, '_version_preview_semaphore'):
            self._version_preview_semaphore = asyncio.Semaphore(4)
        return self._version_preview_semaphore

    def _describe_download_versions(self, versions):
        from .circle_completion_service import SessionLocal
        from ..models.database import ASMRResourceRecord, LibraryOwnedWork, ResourceSourceProbe
        from .resource_source_service import SOURCE, VERSION
        from sqlalchemy import or_, cast
        from sqlalchemy.dialects.postgresql import JSONB
        codes = [item['rjcode'] for item in versions]
        with SessionLocal() as db:
            # ASMRWork.work_status 是 cataloged/downloaded 等工作流状态，不是资源可用结论。
            asmr = {code for (code,) in db.query(ASMRResourceRecord.work_rjcode).filter(
                ASMRResourceRecord.work_rjcode.in_(codes),
                ASMRResourceRecord.source_workno == ASMRResourceRecord.work_rjcode,
                ASMRResourceRecord.source_provider == 'asmr.one',
                ASMRResourceRecord.remote_url.isnot(None), ASMRResourceRecord.remote_url != '').distinct().all()}
            asmr.update(code for (code,) in db.query(CircleWork.asmr_available_rjcode).filter(
                CircleWork.asmr_available_rjcode.in_(codes), CircleWork.has_asmr_one.is_(True),
                or_(CircleWork.is_bonus_work.isnot(True),
                    CircleWork.canonical_rjcode == CircleWork.asmr_available_rjcode)).distinct().all())
            owned = set()
            for row in db.query(LibraryOwnedWork).filter(or_(
                    LibraryOwnedWork.canonical_rjcode.in_(codes),
                    *(cast(LibraryOwnedWork.owned_rjcodes, JSONB).contains([code]) for code in codes))).all():
                owned.update(row.owned_rjcodes or [row.canonical_rjcode])
            sources = {row.rjcode: row for row in db.query(ResourceSourceProbe).filter(
                ResourceSourceProbe.source == SOURCE, ResourceSourceProbe.probe_version == VERSION,
                ResourceSourceProbe.rjcode.in_(codes)).all()}
            for item in versions:
                code = item['rjcode']
                source = sources.get(code)
                item['owned'] = code in owned
                item['resource_sources'] = ([{'id': 'asmr.one', 'label': 'asmr.one'}]
                    if code in asmr else [])
                if source and any(group.get('complete') for group in source.candidates or []):
                    item['resource_sources'].append({'id': SOURCE, 'label': 'YAAS'})
                item['probe_status'] = ('available' if item['resource_sources'] else
                    source.status if source else 'pending')
        return versions

    async def _discover_download_versions(self, context, clicked, refresh=False):
        """合并 DLsite 语言关系与源站实际收录关系；特典不扩散关联。"""
        clicked = self._download_rjcode(clicked)
        if not clicked:
            return []
        context = {**context, 'canonical_rjcode': self._download_rjcode(context.get('canonical_rjcode'))}
        if not context['canonical_rjcode']:
            return []
        if clicked in await asyncio.to_thread(self._unreleased_download_codes, [clicked]):
            return []
        versions = {clicked: dict(rjcode=clicked, title=context['title'], language_label='未知语言')}
        error = ''
        verified_links = []
        source_available = set()
        if not context['is_bonus_work']:
            from .asmr_resource_service import ASMRSourceUnavailableError
            try:
                async with self._download_preview_limiter():
                    linked = await self.dlsite_service.get_linked_works(clicked, refresh=refresh)
                for link in linked.values():
                    data = link if isinstance(link, dict) else link.to_dict()
                    code = self._download_rjcode(data.get('workno'))
                    if (code and data.get('work_type') in {'original', 'translation', 'child_translation'}
                            and data.get('evidence_status') == 'verified'):
                        versions[code] = dict(rjcode=code, title=data.get('title') or code,
                                              language_label=data.get('lang') or '未知语言')
                        verified_links.append({**data, 'rjcode': code})
            except Exception as exc:
                error = str(exc)
            # language_editions 是发行列表，不等于源站收录列表。
            # 只使用源站明确列出的 other_language_editions_in_db，不能以本地
            # 是否曾下载/缓存过文件来判定该语言是否可下载。
            # 展示编号可能是尚未收录的翻译发行页；原作的收录关系仍可指向真实译本。
            seeds = dict.fromkeys([clicked, context['canonical_rjcode']])
            unreleased = await asyncio.to_thread(self._unreleased_download_codes, list(seeds))
            for seed in seeds:
                if seed in unreleased:
                    continue
                try:
                    async with self._download_preview_limiter():
                        work_info, _ = await self.asmr_resource_service._get_remote_source_payload(seed, refresh=refresh)
                    source_available.add(seed)
                    versions.setdefault(seed, dict(rjcode=seed, title=work_info.get('title') or seed,
                                                   language_label='未知语言'))
                    for edition in work_info.get('other_language_editions_in_db') or []:
                        if edition.get('source_type') != 'DLSITE':
                            continue
                        code = self._download_rjcode(edition.get('source_id'))
                        if not code:
                            continue
                        source_available.add(code)
                        previous = versions.get(code) or {}
                        language = previous.get('language_label')
                        if not language or language == '未知语言':
                            language = edition.get('lang') or '未知语言'
                        versions[code] = dict(rjcode=code, title=edition.get('title') or previous.get('title') or code,
                                              language_label=language)
                        if not any(link['rjcode'] == code for link in verified_links):
                            verified_links.append(dict(rjcode=code, lang=language,
                                work_type='original' if edition.get('is_original') else 'translation',
                                evidence_source='asmr.one'))
                except ValueError:
                    pass
                except ASMRSourceUnavailableError as exc:
                    error = str(exc)
            if verified_links:
                await asyncio.to_thread(self._sync_download_version_links, context, verified_links)
        unreleased = await asyncio.to_thread(self._unreleased_download_codes, list(versions))
        descriptors = [dict(context, **versions[code], requested_rjcode=clicked, clicked_rjcode=clicked,
                     resolved_rjcode=code, selected_version=code == clicked,
                     discovery_only=True, discovery_error=error, probe_status='pending')
                for code in [clicked, *sorted(set(versions) - {clicked})] if code not in unreleased]
        descriptors = await asyncio.to_thread(self._describe_download_versions, descriptors)
        for item in descriptors:
            if item['rjcode'] in source_available:
                if not any(source['id'] == 'asmr.one' for source in item['resource_sources']):
                    item['resource_sources'].insert(0, {'id': 'asmr.one', 'label': 'asmr.one'})
                item['probe_status'] = 'available'
        return descriptors

    async def preview_download_version(self, circle_id, canonical_rjcode, rjcode, *, include_resource_sources=True):
        if not hasattr(self, '_version_preview_inflight'):
            self._version_preview_inflight = {}
        key = (circle_id, canonical_rjcode, self.normalize_rjcode(rjcode), include_resource_sources)
        task = self._version_preview_inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._preview_download_version(
                circle_id, canonical_rjcode, rjcode, include_resource_sources=include_resource_sources))
            self._version_preview_inflight[key] = task
            task.add_done_callback(lambda done: self._version_preview_inflight.pop(key, None))
        return deepcopy(await asyncio.shield(task))

    async def _preview_download_version(self, circle_id, canonical_rjcode, rjcode, *, include_resource_sources=True,
                                        available_sources=None):
        context = await asyncio.to_thread(self._download_preview_context, circle_id, canonical_rjcode)
        target = self.normalize_rjcode(rjcode)
        if not target:
            raise ValueError('无效的下载 RJ')
        if target in await asyncio.to_thread(self._unreleased_download_codes, [target]):
            raise ValueError('未发售作品不探测下载来源')
        if context['is_bonus_work']:
            if target != self.normalize_rjcode(context['display_rjcode']):
                raise ValueError('特典只能下载自身精确 RJ')
        elif target not in {context['display_rjcode'], context['canonical_rjcode']}:
            versions = await self._discover_download_versions(context, context['display_rjcode'])
            if target not in {item['rjcode'] for item in versions}:
                raise ValueError('目标 RJ 不在已验证语言关联中')

        async def build_asmr():
            plan = await self.asmr_resource_service.build_download_plan(
                rjcode=target, folder_path='', filters={}, refresh=False, emit_activity_log=False)
            if self.normalize_rjcode(plan.get('rjcode')) != target:
                raise ValueError('资源计划与目标 RJ 不一致')
            resources, skipped = [], []
            reasons = self._build_filter_skip_reasons(plan.get('selectable_resources') or [])
            for resource in plan.get('selectable_resources') or []:
                if resource.get('source_workno') and self.normalize_rjcode(resource['source_workno']) != target:
                    raise ValueError('资源文件与目标 RJ 不一致')
                skip = reasons.get(str(resource.get('relative_path') or ''), [])
                if skip:
                    resource.update(selected=False, recommended_skip_reasons=list(skip))
                    skipped.append(resource)
                else:
                    resources.append(resource)
            plan.update(selectable_resources=resources, filtered_out_resources=skipped,
                        filtered_out_count=len(skipped))
            if hasattr(self.asmr_resource_service, '_group_resources'):
                plan['grouped_resources'] = self.asmr_resource_service._group_resources(resources)
                plan['selection_presets'] = self.asmr_resource_service._build_selection_presets(resources)
            plan.setdefault('summary', {})['selectable_total'] = len(resources)
            return plan

        from .resource_source_service import get_resource_source_service
        async with self._download_preview_limiter():
            if include_resource_sources and available_sources == {'imoutoheaven'}:
                plan = await get_resource_source_service().plan(target, exact=True)
            elif not include_resource_sources or available_sources == {'asmr.one'}:
                plan = await build_asmr()
            else:
                plan = await get_resource_source_service().combine_plan(target, build_asmr, exact=True)
        identity = dict(context, rjcode=target, requested_rjcode=target, resolved_rjcode=target,
                        title=plan.get('title') or context['title'], discovery_only=False,
                        probe_status='available' if plan.get('selectable_resources') or plan.get('filtered_out_resources') else 'missing')
        plan.update(identity)
        for option in plan.get('source_options', []):
            if self.normalize_rjcode(option.get('rjcode')) != target:
                raise ValueError('下载来源与目标 RJ 不一致')
            option.update(identity)
        return plan

    async def preview_batch_download(self, circle_id, canonical_rjcodes, requested_rjcodes=None,
                                     include_resource_sources=False, discovery_only=False, refresh=False):
        from ..config.settings import get_config
        from .library_manager import get_library_manager
        requested = requested_rjcodes or {}

        async def prepare(canonical):
            context = await asyncio.to_thread(self._download_preview_context, circle_id, canonical)
            clicked = self.normalize_rjcode(next(iter(requested.get(canonical) or []), '')) or context['display_rjcode']
            # 特典不接受历史候选字段或本篇编号替代。
            if context['is_bonus_work']:
                clicked = context['display_rjcode']
            versions = await self._discover_download_versions(context, clicked, refresh=refresh)
            # 语言关联只说明作品关系；下载面板只接收来源已有资源证据的版本。
            versions = [item for item in versions if any(
                source['id'] == 'asmr.one' or include_resource_sources
                for source in item.get('resource_sources', []))]
            if discovery_only:
                return versions

            async def materialize(version):
                try:
                    plan = await self._preview_download_version(
                        circle_id, canonical, version['rjcode'],
                        include_resource_sources=include_resource_sources,
                        available_sources={source['id'] for source in version['resource_sources']})
                    if not plan.get('selectable_resources') and not plan.get('filtered_out_resources'):
                        return None
                    return {**version, **plan, 'selected_version': version['rjcode'] == clicked,
                            'language_label': version['language_label'], 'discovery_only': False}
                except ValueError:
                    # 旧资源记录已经失效，不把无资源版本渲染为查询入口。
                    return None

            ready = [plan for plan in await asyncio.gather(*(materialize(item) for item in versions)) if plan]
            if ready and not any(plan['selected_version'] for plan in ready):
                ready[0]['selected_version'] = True
            return ready

        groups = await asyncio.gather(*(prepare(code) for code in dict.fromkeys(canonical_rjcodes)))
        plans = [plan for group in groups for plan in group]
        libraries = await asyncio.to_thread(get_library_manager().list_libraries)
        default = next((item for item in libraries if item.get('is_default')), None) or next(iter(libraries), {})
        return dict(circle_id=circle_id, circle_name=plans[0]['circle_name'] if plans else '', plans=plans,
                    planned_count=len(plans), download_base_path=os.path.join(get_config().storage.temp_path, 'asmr_enhanced'),
                    default_target_library_id=str(default.get('id') or ''), default_target_subdir='')
