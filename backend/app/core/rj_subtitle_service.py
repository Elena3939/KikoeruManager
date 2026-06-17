"""
RJ 字幕抓取服务

功能：
1. 扫描单个 RJ 文件夹或批量父目录
2. 从 asmr.one / DLsite 发现可用中文字幕
3. 下载字幕并执行后处理（去广告、繁转简）
4. 将字幕匹配到本地音频并写入 subtitles/ 目录
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RJSubtitleService:
    """RJ 字幕抓取服务"""

    SUBTITLE_EXTENSIONS = {'.lrc', '.vtt', '.srt', '.ass', '.ssa'}
    AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac'}
    CHINESE_LANGS = {'CHI_HANS', 'CHI_SIMP', 'CHI_HANT', 'CHI_TRAD'}
    # CJK 字符标记：子串匹配即可（几乎不会出现误命中）
    _CHINESE_MARKERS_CJK = frozenset([
        '中文', '汉化', '字幕', '中字', '简中', '简体', '繁中', '繁體', '繁体',
    ])
    # 短英文标记：词边界匹配，避免 'chi' 命中 'achi'、'zh' 命中 'zhang' 等误识别
    _CHINESE_MARKER_EN_RE = re.compile(r'(?<![a-z0-9])(chinese|chs|cht|chi|zh)(?![a-z0-9])', re.IGNORECASE)

    def __init__(self):
        from .asmr_download_service import get_asmr_download_service
        from .subtitle_sync_service import get_subtitle_sync_service

        self.asmr_service = get_asmr_download_service()
        self.subtitle_service = get_subtitle_sync_service()

    def extract_rjcode(self, value: str) -> Optional[str]:
        """从路径或名称中提取 RJ 号"""
        match = re.search(r'[RVB]J(\d{8}|\d{6})(?!\d)', value, re.IGNORECASE)
        if match:
            return match.group(0).upper()
        return None

    def _normalize_scan_depth(self, scan_depth: Optional[int], default: int = 3) -> int:
        try:
            normalized = int(scan_depth if scan_depth is not None else default)
        except (TypeError, ValueError):
            normalized = default
        return max(1, min(normalized, 10))

    def _build_local_scan_result(self, folder: Path) -> Dict:
        rjcode = self.extract_rjcode(folder.name) or self.extract_rjcode(str(folder))
        audio_files = self._collect_audio_files(folder)
        existing_subtitle_count = self._count_existing_subtitles(folder)
        return {
            'rjcode': rjcode,
            'folder_name': folder.name,
            'folder_path': str(folder),
            'audio_count': len(audio_files),
            'existing_subtitle_count': existing_subtitle_count,
            'has_existing_subtitles': existing_subtitle_count > 0,
            'status': self._get_scan_status(len(audio_files), existing_subtitle_count),
        }

    def scan_iter(self, input_path: str, scan_depth: int = 3, progress_callback: Optional[Callable[[str], None]] = None):
        path = Path(input_path)
        if not path.exists():
            raise ValueError("指定路径不存在")
        if not path.is_dir():
            raise ValueError("指定路径不是文件夹")

        for folder in self._iter_discover_rj_folders(path, scan_depth=self._normalize_scan_depth(scan_depth), progress_callback=progress_callback):
            yield self._build_local_scan_result(folder)

    def _iter_discover_rj_folders(self, path: Path, scan_depth: int = 3, progress_callback: Optional[Callable[[str], None]] = None):
        if self.extract_rjcode(path.name):
            yield path
            return

        seen = set()

        def walk(folder: Path, depth_left: int):
            if depth_left <= 0:
                return
            if progress_callback:
                try:
                    progress_callback(str(folder))
                except Exception:
                    logger.debug('[RJ字幕] 本地扫描进度回调失败: %s', folder, exc_info=True)
            try:
                children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
            except (FileNotFoundError, PermissionError, OSError):
                return
            for child in children:
                if not child.is_dir():
                    continue
                if child.name.lower() == 'subtitles':
                    continue
                if self.extract_rjcode(child.name):
                    try:
                        resolved = str(child.resolve())
                    except OSError:
                        resolved = str(child)
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    yield child
                    continue
                yield from walk(child, depth_left - 1)

        yield from walk(path, self._normalize_scan_depth(scan_depth))

    def scan(self, input_path: str, scan_depth: int = 3) -> List[Dict]:
        """扫描输入路径，返回可处理的 RJ 文件夹列表"""
        path = Path(input_path)
        if not path.exists():
            raise ValueError("指定路径不存在")
        if not path.is_dir():
            raise ValueError("指定路径不是文件夹")

        candidates = self._discover_rj_folders(path, scan_depth=self._normalize_scan_depth(scan_depth))
        results = []
        for folder in candidates:
            rjcode = self.extract_rjcode(folder.name) or self.extract_rjcode(str(folder))
            audio_files = self._collect_audio_files(folder)
            existing_subtitle_count = self._count_existing_subtitles(folder)
            results.append({
                'rjcode': rjcode,
                'folder_name': folder.name,
                'folder_path': str(folder),
                'audio_count': len(audio_files),
                'existing_subtitle_count': existing_subtitle_count,
                'has_existing_subtitles': existing_subtitle_count > 0,
                'status': self._get_scan_status(len(audio_files), existing_subtitle_count),
            })

        results.sort(key=lambda item: item['rjcode'] or item['folder_name'])
        return results

    def _discover_rj_folders(self, path: Path, scan_depth: int = 3) -> List[Path]:
        """发现 RJ 文件夹"""
        if self.extract_rjcode(path.name):
            return [path]

        discovered: List[Path] = []
        seen = set()

        def walk(folder: Path, depth_left: int):
            if depth_left <= 0:
                return
            try:
                children = list(folder.iterdir())
            except (FileNotFoundError, PermissionError, OSError):
                return
            for child in children:
                if not child.is_dir():
                    continue
                if child.name.lower() == 'subtitles':
                    continue
                if self.extract_rjcode(child.name):
                    resolved = str(child.resolve())
                    if resolved in seen:
                        continue
                    discovered.append(child)
                    seen.add(resolved)
                    continue
                walk(child, depth_left - 1)

        walk(path, self._normalize_scan_depth(scan_depth))
        return discovered

    def _get_scan_status(self, audio_count: int, existing_subtitle_count: int) -> str:
        if audio_count == 0:
            return 'no_audio'
        if existing_subtitle_count > 0:
            return 'existing'
        return 'ready'

    def _collect_audio_files(self, folder: Path) -> List[str]:
        """收集 RJ 文件夹中的音频文件，跳过 subtitles/"""
        audio_files = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [name for name in dirs if name.lower() != 'subtitles']
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.AUDIO_EXTENSIONS:
                    audio_files.append(os.path.join(root, file))
        audio_files.sort()
        return audio_files

    def _count_existing_subtitles(self, folder: Path) -> int:
        subtitle_dir = folder / 'subtitles'
        if not subtitle_dir.exists():
            return 0

        count = 0
        for root, _dirs, files in os.walk(subtitle_dir):
            for file in files:
                if os.path.splitext(file)[1].lower() in self.SUBTITLE_EXTENSIONS:
                    count += 1
        return count

    def _is_remote_subtitles_relative_path(self, relative_path: str) -> bool:
        normalized = str(PurePosixPath(relative_path or '')).replace('\\', '/').lower().lstrip('/')
        return normalized == 'subtitles' or normalized.startswith('subtitles/')

    def _collect_remote_audio_entries(self, items: List[Dict]) -> List[Dict]:
        audio_entries = []
        for item in items:
            relative_path = item.get('relative_path') or item.get('name') or ''
            if self._is_remote_subtitles_relative_path(relative_path):
                continue
            ext = os.path.splitext(item.get('name') or '')[1].lower()
            if ext not in self.AUDIO_EXTENSIONS:
                continue
            audio_entries.append({
                'path': item.get('path') or relative_path,
                'name': item.get('name') or os.path.basename(relative_path),
                'relative_path': relative_path,
            })
        audio_entries.sort(key=lambda item: item.get('relative_path') or item.get('name') or '')
        return audio_entries

    def _count_remote_existing_subtitles(self, items: List[Dict]) -> int:
        count = 0
        for item in items:
            relative_path = item.get('relative_path') or item.get('name') or ''
            if not self._is_remote_subtitles_relative_path(relative_path):
                continue
            if os.path.splitext(item.get('name') or '')[1].lower() in self.SUBTITLE_EXTENSIONS:
                count += 1
        return count

    async def check_kikoeru_existing_subtitles(self, rjcode: str) -> Dict[str, Any]:
        """检查 Kikoeru 中该作品或其关联作品是否已经存在可用字幕。"""
        from .kikoeru_duplicate_service import get_kikoeru_service

        normalized_rjcode = str(rjcode or '').strip().upper()
        empty_state = {
            'checked': False,
            'checked_rjcode': normalized_rjcode,
            'has_work': False,
            'has_existing_subtitles': False,
            'matched_rjcode': '',
            'subtitle_file_count': 0,
            'subtitle_check_source': '',
            'title': '',
            'matches': [],
            'error': '',
        }
        if not normalized_rjcode:
            return empty_state

        service = get_kikoeru_service()
        if not getattr(service.config, 'enabled', False):
            return {
                **empty_state,
                'error': 'kikoeru_disabled',
            }

        try:
            results = await service.check_duplicate_with_linkages(normalized_rjcode, use_cache=True)
        except Exception as exc:
            logger.warning('[RJ字幕] 查询 Kikoeru 字幕状态失败: rj=%s error=%s', normalized_rjcode, exc)
            return {
                **empty_state,
                'error': str(exc),
            }

        matches: List[Dict[str, Any]] = []
        has_work = False
        for workno, result in (results or {}).items():
            if not result or not getattr(result, 'is_found', False):
                continue
            has_work = True
            subtitle_count = int(getattr(result, 'subtitle_file_count', 0) or 0)
            subtitle_check_source = str(getattr(result, 'subtitle_check_source', '') or '').strip()
            has_subtitles = bool(getattr(result, 'has_lyric_hint', False))
            if not has_subtitles or not subtitle_check_source or subtitle_check_source == 'search_only':
                continue
            matches.append({
                'rjcode': str(workno or getattr(result, 'rjcode', '') or '').upper(),
                'subtitle_file_count': subtitle_count,
                'subtitle_check_source': subtitle_check_source,
                'title': str(getattr(result, 'title', '') or ''),
                'match_type': str(getattr(result, 'match_type', '') or ''),
            })

        preferred_match = next((item for item in matches if item['rjcode'] == normalized_rjcode), None)
        if preferred_match is None and matches:
            preferred_match = matches[0]

        return {
            'checked': True,
            'checked_rjcode': normalized_rjcode,
            'has_work': has_work,
            'has_existing_subtitles': bool(preferred_match),
            'matched_rjcode': str(preferred_match.get('rjcode') or '') if preferred_match else '',
            'subtitle_file_count': int(preferred_match.get('subtitle_file_count') or 0) if preferred_match else 0,
            'subtitle_check_source': str(preferred_match.get('subtitle_check_source') or '') if preferred_match else '',
            'title': str(preferred_match.get('title') or '') if preferred_match else '',
            'matches': matches,
            'error': '',
        }

    async def _discover_remote_rj_folders(
        self,
        manager,
        client,
        folder_path: str,
        scan_depth: int,
    ) -> List[str]:
        discovered: List[str] = []
        seen: set[str] = set()

        async def walk(current_path: str, depth_left: int):
            if depth_left <= 0:
                return
            children = await manager._list_remote_directory(client, current_path)
            for child in children:
                name = child.get('name') or ''
                if manager._should_skip_entry(name) or name.lower() == 'subtitles':
                    continue
                if not child.get('isdir', False):
                    continue
                raw_child_path = child.get('path') or child.get('real_path') or ''
                child_path = manager._normalize_remote_path(raw_child_path)
                if not raw_child_path or (child_path == '/' and current_path != '/'):
                    child_path = manager._normalize_remote_path(str(PurePosixPath(current_path) / name))
                if child_path in {'/', current_path} and name:
                    logger.warning('[RJ字幕] 跳过异常远程目录路径: parent=%s name=%s raw=%s normalized=%s', current_path, name, raw_child_path, child_path)
                    continue
                if self.extract_rjcode(name):
                    if child_path in seen:
                        continue
                    discovered.append(child_path)
                    seen.add(child_path)
                    continue
                await walk(child_path, depth_left - 1)

        await walk(folder_path, self._normalize_scan_depth(scan_depth))
        return discovered

    async def scan_remote(self, library_id: str, folder_path: str, scan_depth: int = 3) -> List[Dict]:
        from .library_manager import get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if library.type != 'synology_filestation':
            raise ValueError('指定库存不是远程库存')
        if not library.synology:
            raise RuntimeError('远程库存未配置群晖连接参数')

        normalized_path = manager._normalize_remote_path(folder_path)
        browse_root = manager._normalize_remote_path(library.browse_root_path or library.root_path or '/')
        if not manager._remote_path_is_within_root(normalized_path, browse_root):
            raise PermissionError('目标路径不在当前库存范围内')

        client = manager.get_cached_synology_client(library.synology)
        info = await client.stat(normalized_path)
        info_item = manager._first_remote_info_item(info)
        if not info_item or not info_item.get('isdir', False):
            raise FileNotFoundError('目标文件夹不存在')

        folder_name = PurePosixPath(normalized_path).name or normalized_path
        if self.extract_rjcode(folder_name):
            candidates = [normalized_path]
        else:
            candidates = await self._discover_remote_rj_folders(
                manager,
                client,
                normalized_path,
                scan_depth=self._normalize_scan_depth(scan_depth),
            )

        results = []
        for candidate in candidates:
            try:
                folder_info = await manager.folder_contents(library_id, candidate, client=client, prefer_index=False)
            except Exception as exc:
                logger.warning('[RJ字幕] 跳过不可访问的远程候选目录: %s (%s)', candidate, exc)
                continue
            remote_items = folder_info.get('items') or []
            audio_entries = self._collect_remote_audio_entries(remote_items)
            existing_subtitle_count = self._count_remote_existing_subtitles(remote_items)
            candidate_name = PurePosixPath(candidate).name or candidate
            results.append({
                'rjcode': self.extract_rjcode(candidate_name) or self.extract_rjcode(candidate),
                'folder_name': candidate_name,
                'folder_path': candidate,
                'audio_count': len(audio_entries),
                'existing_subtitle_count': existing_subtitle_count,
                'has_existing_subtitles': existing_subtitle_count > 0,
                'status': self._get_scan_status(len(audio_entries), existing_subtitle_count),
            })

        results.sort(key=lambda item: item['rjcode'] or item['folder_name'])
        return results

    # Override the legacy batch-only scan helpers with streaming-friendly versions.
    def scan(self, input_path: str, scan_depth: int = 3) -> List[Dict]:
        results = list(self.scan_iter(input_path, scan_depth=scan_depth))
        results.sort(key=lambda item: item['rjcode'] or item['folder_name'])
        return results

    def _discover_rj_folders(self, path: Path, scan_depth: int = 3) -> List[Path]:
        return list(self._iter_discover_rj_folders(path, scan_depth=scan_depth))

    async def _iter_discover_remote_rj_folders(
        self,
        manager,
        client,
        folder_path: str,
        scan_depth: int,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        """并发版目录发现：同级目录并行探索，然后逐个 yield 结果。"""
        seen: set[str] = set()

        async def collect(current_path: str, depth_left: int) -> List[str]:
            """递归并发收集 current_path 下所有 RJ 目录路径。"""
            if depth_left <= 0:
                return []
            if progress_callback:
                try:
                    progress_callback(current_path)
                except Exception:
                    logger.debug('[RJ字幕] 远程扫描进度回调失败: %s', current_path, exc_info=True)
            children = await manager._list_remote_directory(client, current_path)
            rj_paths: List[str] = []
            recurse_paths: List[str] = []
            for child in sorted(children, key=lambda item: str(item.get('name') or '').lower()):
                name = child.get('name') or ''
                if manager._should_skip_entry(name) or name.lower() == 'subtitles':
                    continue
                if not child.get('isdir', False):
                    continue
                raw_child_path = child.get('path') or child.get('real_path') or ''
                child_path = manager._normalize_remote_path(raw_child_path)
                if not raw_child_path or (child_path == '/' and current_path != '/'):
                    child_path = manager._normalize_remote_path(str(PurePosixPath(current_path) / name))
                if child_path in {'/', current_path} and name:
                    logger.warning('[RJ字幕] 跳过异常远程目录路径: parent=%s name=%s raw=%s normalized=%s', current_path, name, raw_child_path, child_path)
                    continue
                if self.extract_rjcode(name):
                    if child_path not in seen:
                        seen.add(child_path)
                        rj_paths.append(child_path)
                else:
                    recurse_paths.append(child_path)
            # 对非 RJ 子目录并发递归
            if recurse_paths and depth_left > 1:
                sub_results = await asyncio.gather(
                    *[collect(p, depth_left - 1) for p in recurse_paths],
                    return_exceptions=True,
                )
                for result in sub_results:
                    if isinstance(result, list):
                        rj_paths.extend(result)
            return rj_paths

        all_paths = await collect(folder_path, self._normalize_scan_depth(scan_depth))
        for path in all_paths:
            yield path


    async def _discover_remote_rj_folders(
        self,
        manager,
        client,
        folder_path: str,
        scan_depth: int,
    ) -> List[str]:
        discovered: List[str] = []
        async for candidate in self._iter_discover_remote_rj_folders(manager, client, folder_path, scan_depth):
            discovered.append(candidate)
        return discovered

    async def _build_remote_scan_result(self, manager, library_id: str, candidate: str, *, client=None) -> Optional[Dict]:
        try:
            folder_info = await manager.folder_contents(library_id, candidate, client=client, prefer_index=False)
        except Exception as exc:
            logger.warning('[RJ字幕] 跳过不可访问的远程候选目录: %s (%s)', candidate, exc)
            return None

        remote_items = folder_info.get('items') or []
        audio_entries = self._collect_remote_audio_entries(remote_items)
        existing_subtitle_count = self._count_remote_existing_subtitles(remote_items)
        candidate_name = PurePosixPath(candidate).name or candidate
        return {
            'rjcode': self.extract_rjcode(candidate_name) or self.extract_rjcode(candidate),
            'folder_name': candidate_name,
            'folder_path': candidate,
            'audio_count': len(audio_entries),
            'existing_subtitle_count': existing_subtitle_count,
            'has_existing_subtitles': existing_subtitle_count > 0,
            'status': self._get_scan_status(len(audio_entries), existing_subtitle_count),
        }

    async def scan_remote_iter(self, library_id: str, folder_path: str, scan_depth: int = 3, progress_callback: Optional[Callable[[str], None]] = None):
        from .library_manager import get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if library.type != 'synology_filestation':
            raise ValueError('指定库存不是远程库存')
        if not library.synology:
            raise RuntimeError('远程库存未配置群晖连接参数')

        normalized_path = manager._normalize_remote_path(folder_path)
        browse_root = manager._normalize_remote_path(library.browse_root_path or library.root_path or '/')
        if not manager._remote_path_is_within_root(normalized_path, browse_root):
            raise PermissionError('目标路径不在当前库存范围内')

        # 使用全局缓存 client，避免重复登录
        client = manager.get_cached_synology_client(library.synology)
        info = await client.stat(normalized_path)
        info_item = manager._first_remote_info_item(info)
        if not info_item or not info_item.get('isdir', False):
            raise FileNotFoundError('目标文件夹不存在')

        folder_name = PurePosixPath(normalized_path).name or normalized_path
        if self.extract_rjcode(folder_name):
            result = await self._build_remote_scan_result(manager, library_id, normalized_path, client=client)
            if result:
                yield result
            return

        # 阶段一：并发发现所有 RJ 候选目录
        candidates: List[str] = []
        async for candidate in self._iter_discover_remote_rj_folders(
            manager,
            client,
            normalized_path,
            scan_depth=self._normalize_scan_depth(scan_depth),
            progress_callback=progress_callback,
        ):
            candidates.append(candidate)

        if not candidates:
            return

        # 阶段二：并发读取各候选目录内容（最多 8 路并发，避免压垮 NAS）
        semaphore = asyncio.Semaphore(8)

        async def bounded_build(cand: str) -> Optional[Dict]:
            async with semaphore:
                return await self._build_remote_scan_result(manager, library_id, cand, client=client)

        build_results = await asyncio.gather(
            *[bounded_build(c) for c in candidates],
            return_exceptions=True,
        )
        for result in build_results:
            if isinstance(result, dict):
                yield result

    async def scan_remote(self, library_id: str, folder_path: str, scan_depth: int = 3) -> List[Dict]:
        results = []
        async for item in self.scan_remote_iter(library_id, folder_path, scan_depth=scan_depth):
            results.append(item)
        results.sort(key=lambda item: item['rjcode'] or item['folder_name'])
        return results

    def _sanitize_relative_path(self, relative_path: str) -> str:
        parts = []
        for part in Path(relative_path).parts:
            if part in ('', '.', '..'):
                continue
            cleaned = re.sub(r'[<>:"|?*]', '_', part).strip()
            if cleaned:
                parts.append(cleaned)
        if not parts:
            return 'subtitle.lrc'
        return os.path.join(*parts)

    def _has_chinese_marker(self, text: str) -> bool:
        lowered = text.lower()
        # 先检 CJK 标记（快速路径）
        if any(marker in lowered for marker in self._CHINESE_MARKERS_CJK):
            return True
        # 再用词边界 regex 检英文标记，避免 'chi' 命中 'achi' 等误识别
        return bool(self._CHINESE_MARKER_EN_RE.search(lowered))

    def _strip_trailing_audio_extension(self, name: str) -> str:
        stripped = name or ''
        while stripped:
            base, ext = os.path.splitext(stripped)
            if ext.lower() not in self.AUDIO_EXTENSIONS:
                break
            stripped = base
        return stripped

    def _extract_trailing_audio_extension(self, name: str) -> str:
        current = name or ''
        detected = ''
        while current:
            base, ext = os.path.splitext(current)
            if ext.lower() not in self.AUDIO_EXTENSIONS:
                break
            detected = ext.lower()
            current = base
        return detected

    def _resolve_subtitle_name(self, subtitle: Dict) -> str:
        return (
            subtitle.get('name')
            or subtitle.get('title')
            or os.path.basename(str(subtitle.get('path') or subtitle.get('relative_path') or ''))
        )

    def _normalize_subtitle_file(self, subtitle: Dict) -> Dict:
        normalized = dict(subtitle or {})
        name = self._resolve_subtitle_name(normalized)
        path = str(normalized.get('path') or normalized.get('relative_path') or name)
        ext = str(normalized.get('ext') or os.path.splitext(name)[1].lower())
        base_name = normalized.get('base_name')
        if not base_name:
            base_name = os.path.splitext(name)[0]
        original_base_name = str(base_name)
        base_name = self._strip_trailing_audio_extension(str(base_name))
        normalized.update({
            'name': name,
            'path': path,
            'ext': ext,
            'base_name': base_name,
            'source_audio_ext': self._extract_trailing_audio_extension(original_base_name),
        })
        return normalized

    def _resolve_naming_strategy(self, naming_strategy: Optional[str]) -> str:
        strategy = str(naming_strategy or 'audio').strip().lower()
        return strategy if strategy in {'audio', 'subtitle'} else 'audio'

    def _normalize_identity_path(self, path_value: str) -> str:
        raw_path = str(path_value or '').replace('\\', '/').strip('/')
        if not raw_path:
            return ''
        raw_path = self._strip_subtitle_extension(raw_path)
        raw_path = self._strip_trailing_audio_extension(raw_path)
        normalized_parts = []
        for part in raw_path.split('/'):
            normalized_part = self._normalize_name(part)
            if normalized_part:
                normalized_parts.append(normalized_part)
        return '/'.join(normalized_parts)

    def _normalize_name(self, name: str) -> str:
        normalized = self._strip_trailing_audio_extension(name or '').lower()
        normalized = re.sub(r'^(track|trk|tr)[_\-\s]*', '', normalized)
        normalized = re.sub(r'[\s_\-]+', '', normalized)
        normalized = re.sub(r'[『』「」\[\]【】（）()<>《》]', '', normalized)
        normalized = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u30ff]+', '', normalized)
        return normalized

    def _extract_track_number(self, name: str) -> Optional[int]:
        return self.subtitle_service._extract_track_number(name)

    def _read_audio_metadata(self, audio_path: str) -> Dict:
        """读取音频 metadata，失败时静默降级"""
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(audio_path, easy=True)
            if not audio or not getattr(audio, 'tags', None):
                return {}

            tags = audio.tags
            track = None
            title = None

            if 'tracknumber' in tags and tags['tracknumber']:
                raw_track = str(tags['tracknumber'][0]).split('/')[0].strip()
                if raw_track.isdigit():
                    track = int(raw_track)

            if 'title' in tags and tags['title']:
                title = str(tags['title'][0]).strip()

            return {
                'track_number': track,
                'title': title,
                'normalized_title': self._normalize_name(title or ''),
            }
        except Exception:
            return {}

    def _build_work_search_order(self, rjcode: str, linked_works: List) -> List:
        """构建作品搜索顺序：当前 RJ -> 中文关联 -> 原作 -> 其他。"""
        ordered = []
        seen = set()

        def append_work(work):
            if not work or work.workno in seen:
                return
            ordered.append(work)
            seen.add(work.workno)

        current = next((work for work in linked_works if work.workno.upper() == rjcode.upper()), None)
        append_work(current)

        for work in linked_works:
            if getattr(work, 'lang', '') in self.CHINESE_LANGS:
                append_work(work)

        for work in linked_works:
            if getattr(work, 'work_type', '') == 'original':
                append_work(work)

        for work in linked_works:
            append_work(work)

        return ordered

    def _normalize_work_lang(self, lang: Optional[str]) -> str:
        raw_lang = str(lang or '').strip()
        normalized = raw_lang.upper().replace('-', '_')
        alias_map = {
            'ZH_CN': 'CHI_HANS',
            'ZH_HANS': 'CHI_HANS',
            'CHS': 'CHI_HANS',
            '简体中文': 'CHI_HANS',
            '簡体中文': 'CHI_HANS',
            'ZH_TW': 'CHI_HANT',
            'ZH_HANT': 'CHI_HANT',
            'CHT': 'CHI_HANT',
            '繁体中文': 'CHI_HANT',
            '繁體中文': 'CHI_HANT',
            '日文': 'JPN',
            '日本語': 'JPN',
            '日语': 'JPN',
            '日語': 'JPN',
        }
        return alias_map.get(normalized, alias_map.get(raw_lang, normalized or 'JPN'))

    def _build_work_search_order_from_work_info(self, rjcode: str, work_info: Dict) -> List:
        from .asmr_download_service import LinkedWorkInfo

        requested = (rjcode or '').upper()
        language_editions = work_info.get('language_editions') or []
        if isinstance(language_editions, dict):
            language_editions = list(language_editions.values())
        other_language_editions = work_info.get('other_language_editions_in_db') or []
        if isinstance(other_language_editions, dict):
            other_language_editions = list(other_language_editions.values())
        translation_info = work_info.get('translation_info') or {}

        requested_lang = 'JPN'
        works = []
        seen = set()

        def append_work(workno: str, lang: str = 'JPN', work_type: str = 'translation'):
            normalized = (workno or '').upper()
            if not normalized:
                return
            if not normalized.startswith(('RJ', 'BJ', 'VJ')):
                normalized = f"RJ{normalized}"
            if normalized in seen:
                return
            works.append(LinkedWorkInfo(normalized, self._normalize_work_lang(lang), work_type))
            seen.add(normalized)

        for edition in language_editions:
            workno = (edition.get('workno') or '').upper()
            lang = self._normalize_work_lang(edition.get('lang') or 'JPN')
            if workno == requested:
                requested_lang = lang
                break

        append_work(requested, requested_lang, 'requested')
        append_work(work_info.get('source_id') or work_info.get('original_workno'), 'JPN', 'original')
        append_work(translation_info.get('parent_workno'), requested_lang, 'parent')

        for edition in language_editions:
            append_work(edition.get('workno'), edition.get('lang') or 'JPN', 'translation')

        for child_workno in translation_info.get('child_worknos') or []:
            append_work(child_workno, requested_lang, 'child')

        for edition in other_language_editions:
            append_work(
                edition.get('source_id') or edition.get('workno') or edition.get('id'),
                edition.get('lang') or edition.get('label') or 'JPN',
                'translation',
            )

        return self._build_work_search_order(rjcode, works)

    def _collect_subtitle_candidates(self, work, files: List[Dict]) -> List[Dict]:
        """从文件列表中筛选候选字幕"""
        candidates = []
        for file_info in files:
            raw_title = file_info.get('title', '')
            raw_path = file_info.get('path', raw_title)
            display_title = file_info.get('display_title') or raw_title
            display_path = file_info.get('display_path') or raw_path
            title = display_title or raw_title
            path = display_path or raw_path or title
            ext = os.path.splitext(raw_title or title)[1].lower()
            if ext not in self.SUBTITLE_EXTENSIONS:
                continue

            url = file_info.get('media_download_url') or file_info.get('download_url')
            if not url:
                continue

            combined_text = f"{path} {title} {raw_path} {raw_title}".lower()
            has_marker = self._has_chinese_marker(combined_text)

            if getattr(work, 'lang', '') in self.CHINESE_LANGS:
                score = 200 if has_marker else 150
            elif has_marker:
                score = 120
            else:
                continue

            candidates.append({
                **file_info,
                'name': title or os.path.basename(path),
                'ext': ext,
                'base_name': self._strip_trailing_audio_extension(os.path.splitext(title or os.path.basename(path))[0]),
                'media_download_url': url,
                'subtitle_score': score,
                'relative_path': path or title,
                'source_name': raw_title or title,
                'source_relative_path': raw_path or path,
                'has_chinese_marker': has_marker,
            })

        candidates.sort(key=lambda item: (-item['subtitle_score'], item.get('path', '')))
        return candidates

    async def find_best_subtitle_source(
        self,
        rjcode: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[Dict], List[Dict]]:
        """查找最合适的中文字幕来源（并发搜索所有候选版本，按优先级选最优）"""
        initial_work_info = None
        if progress_callback:
            progress_callback(12, f"获取 ASMR 作品信息 {rjcode}")
        initial_work_info = await self.asmr_service.fetch_work_info(rjcode)
        if initial_work_info:
            ordered_works = self._build_work_search_order_from_work_info(rjcode, initial_work_info)
        else:
            if progress_callback:
                progress_callback(12, f"查询 DLsite 关联版本 {rjcode}")
            linked_works = await self.asmr_service.get_linked_works_from_dlsite(rjcode)
            ordered_works = self._build_work_search_order(rjcode, linked_works)

        logger.info(
            "[RJ字幕] %s 候选版本顺序: %s",
            rjcode,
            [(work.workno, getattr(work, 'lang', ''), getattr(work, 'work_type', '')) for work in ordered_works],
        )

        if progress_callback:
            progress_callback(16, f"已发现 {len(ordered_works)} 个候选版本，并发搜索字幕...")

        # 并发搜索所有候选版本（限 3 路并发，避免对 asmr.one 过度请求）
        semaphore = asyncio.Semaphore(3)

        async def fetch_one(work):
            """Fetch work info + track list for one candidate."""
            async with semaphore:
                is_initial = (initial_work_info is not None and work.workno.upper() == rjcode.upper())
                work_info = initial_work_info if is_initial else await self.asmr_service.fetch_work_info(work.workno)
                if not work_info:
                    return None, None
                tracks = await self.asmr_service.fetch_track_list(work.workno)
                flat_files = self.asmr_service._flatten_tracks(tracks or [])
                subtitle_files = self._collect_subtitle_candidates(work, flat_files)
                return subtitle_files, work_info

        tasks = [asyncio.create_task(fetch_one(work)) for work in ordered_works]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        if progress_callback:
            progress_callback(26, "并发搜索完成，选择最优来源...")

        # 按原始优先级顺序评估结果，取最高优先级且有字幕的版本
        attempts: List[Dict] = []
        best_source: Optional[Dict] = None
        for work, raw in zip(ordered_works, raw_results):
            if isinstance(raw, BaseException):
                logger.warning("[RJ字幕] 候选版本查询异常: rj=%s error=%s", work.workno, raw)
                attempts.append({
                    'rjcode': work.workno,
                    'lang': getattr(work, 'lang', ''),
                    'work_type': getattr(work, 'work_type', ''),
                    'subtitle_count': 0,
                    'reason': f'查询异常: {raw}',
                })
                continue
            subtitle_files, work_info = raw
            if work_info is None:
                attempts.append({
                    'rjcode': work.workno,
                    'lang': getattr(work, 'lang', ''),
                    'work_type': getattr(work, 'work_type', ''),
                    'subtitle_count': 0,
                    'reason': '作品不存在或不可访问',
                })
                continue
            subtitle_files = subtitle_files or []
            attempts.append({
                'rjcode': work.workno,
                'lang': getattr(work, 'lang', ''),
                'work_type': getattr(work, 'work_type', ''),
                'subtitle_count': len(subtitle_files),
                'title': work_info.get('title', ''),
            })
            if subtitle_files and best_source is None:
                # 取最先遇到的（即最高优先级）有字幕版本
                best_source = {
                    'rjcode': work.workno,
                    'lang': getattr(work, 'lang', ''),
                    'work_type': getattr(work, 'work_type', ''),
                    'title': work_info.get('title', ''),
                    'subtitle_files': subtitle_files,
                }

        return best_source, attempts

    def _build_audio_index(self, audio_files: List[Any], enable_metadata_match: bool = True) -> List[Dict]:
        audio_index = []
        for audio_item in audio_files:
            if isinstance(audio_item, dict):
                audio_path = str(audio_item.get('path') or audio_item.get('relative_path') or audio_item.get('name') or '')
                display_name = str(audio_item.get('name') or os.path.basename(audio_path) or audio_path)
                metadata = dict(audio_item.get('metadata') or {})
            else:
                audio_path = str(audio_item)
                display_name = os.path.basename(audio_path)
                metadata = {}

            basename = os.path.splitext(display_name)[0]
            if enable_metadata_match and not metadata and audio_path and os.path.exists(audio_path):
                metadata = self._read_audio_metadata(audio_path)

            audio_index.append({
                'path': audio_path,
                'display_name': display_name,
                'base_name': basename,
                'normalized_name': self._normalize_name(basename),
                'track_number': self._extract_track_number(basename),
                'metadata': metadata,
            })
        audio_index.sort(key=lambda item: item['base_name'])
        return audio_index

    def _group_subtitles(self, subtitle_files: List[Dict]) -> List[Dict]:
        groups = defaultdict(list)
        for subtitle in subtitle_files:
            normalized_subtitle = self._normalize_subtitle_file(subtitle)
            groups[normalized_subtitle['base_name']].append(normalized_subtitle)

        grouped = []
        for base_name, files in groups.items():
            deduplicated_by_ext: Dict[str, Dict] = {}
            for item in files:
                dedupe_key = item.get('ext') or ''
                existing = deduplicated_by_ext.get(dedupe_key)
                if existing is None:
                    deduplicated_by_ext[dedupe_key] = item
                    continue

                candidate_rank = (
                    0 if not item.get('source_audio_ext') else 1,
                    len(item.get('name') or ''),
                    item.get('name') or '',
                )
                existing_rank = (
                    0 if not existing.get('source_audio_ext') else 1,
                    len(existing.get('name') or ''),
                    existing.get('name') or '',
                )
                if candidate_rank < existing_rank:
                    deduplicated_by_ext[dedupe_key] = item

            grouped.append({
                'base_name': base_name,
                'normalized_name': self._normalize_name(base_name),
                'track_number': self._extract_track_number(base_name),
                'files': sorted(deduplicated_by_ext.values(), key=lambda item: item['name']),
            })

        grouped.sort(key=lambda item: item['base_name'])
        return grouped

    def _pick_download_candidate(self, existing: Optional[Dict], candidate: Dict, preferred_audio_exts: List[str]) -> Dict:
        if existing is None:
            return candidate

        def rank(item: Dict) -> Tuple[int, int, int, str]:
            source_audio_ext = item.get('source_audio_ext') or ''
            preferred_index = preferred_audio_exts.index(source_audio_ext) if source_audio_ext in preferred_audio_exts else 99
            return (
                0 if source_audio_ext == '.wav' else 1,
                0 if source_audio_ext in preferred_audio_exts else 1,
                preferred_index,
                0 if not source_audio_ext else 1,
                item.get('name') or '',
            )

        return candidate if rank(candidate) < rank(existing) else existing

    def _preferred_subtitle_source_audio_exts(self, audio_files: List[Any]) -> List[str]:
        preferred_order = ['.wav', '.flac', '.m4a', '.mp3', '.ogg', '.aac', '.wma']
        detected_exts = []
        for audio in audio_files:
            if isinstance(audio, dict):
                raw_name = audio.get('name') or audio.get('display_name') or audio.get('path') or ''
            else:
                raw_name = str(audio or '')
            ext = os.path.splitext(str(raw_name))[1].lower()
            if ext in self.AUDIO_EXTENSIONS and ext not in detected_exts:
                detected_exts.append(ext)

        ordered_detected = [ext for ext in preferred_order if ext in detected_exts]
        return ordered_detected or preferred_order

    def _strip_subtitle_extension(self, value: str) -> str:
        current = str(value or '')
        base, ext = os.path.splitext(current)
        if ext.lower() in self.SUBTITLE_EXTENSIONS:
            return base
        return current

    def _rule_value(self, rule: Any, key: str, default=None):
        if isinstance(rule, dict):
            return rule.get(key, default)
        return getattr(rule, key, default)

    def _normalize_subtitle_filter_target(self, target: Any) -> str:
        normalized = str(target or 'name').strip().lower()
        if normalized in {'name', 'file', 'filename'}:
            return 'name'
        if normalized in {'path', 'folder', 'filepath'}:
            return 'path'
        if normalized == 'all':
            return 'all'
        return 'name'

    def _build_subtitle_filter_candidates(self, *values: str) -> List[str]:
        candidates: List[str] = []
        for raw in values:
            text = str(raw or '')
            if not text:
                continue
            variants = {
                text,
                text.replace('效果音', '音效'),
                text.replace('効果音', '音效'),
                text.replace('sound effect', 'sound'),
                text.replace('sound effects', 'sound'),
                text.replace('sfx', 'sound'),
            }
            normalized_spaces = set()
            for item in variants:
                normalized_spaces.add(item)
                normalized_spaces.add(re.sub(r'[\s_\-]+', '', item))
            for item in normalized_spaces:
                if item and item not in candidates:
                    candidates.append(item)
        return candidates

    def _apply_subtitle_filter_rules(self, subtitle_files: List[Dict], filter_rules: List[Any]) -> List[Dict]:
        if not filter_rules:
            return subtitle_files

        active_rules = [
            rule for rule in filter_rules
            if bool(self._rule_value(rule, 'enabled', True))
            and str(self._rule_value(rule, 'action', 'exclude') or 'exclude').lower() == 'exclude'
            and str(self._rule_value(rule, 'pattern', '') or '').strip()
        ]
        if not active_rules:
            logger.info('[RJ字幕] 已启用字幕过滤，但当前没有有效规则，候选保持 %s 个', len(subtitle_files))
            return [self._normalize_subtitle_file(item) for item in subtitle_files]

        filtered: List[Dict] = []
        excluded_count = 0

        for subtitle in subtitle_files:
            normalized = self._normalize_subtitle_file(subtitle)
            subtitle_name = normalized.get('name') or ''
            subtitle_path = str(normalized.get('relative_path') or normalized.get('path') or subtitle_name)
            display_name = str(normalized.get('display_name') or subtitle_name)
            source_name_raw = str(normalized.get('source_name') or subtitle_name)
            source_name = self._strip_subtitle_extension(subtitle_name)
            source_path = self._strip_subtitle_extension(subtitle_path)
            display_source_name = self._strip_subtitle_extension(display_name)
            source_name_clean = self._strip_subtitle_extension(source_name_raw)

            excluded = False
            for rule in active_rules:
                pattern = str(self._rule_value(rule, 'pattern', '') or '')
                rule_name = str(self._rule_value(rule, 'name', '过滤规则') or '过滤规则')
                target = self._normalize_subtitle_filter_target(self._rule_value(rule, 'target', 'name'))

                if target == 'path':
                    candidates = self._build_subtitle_filter_candidates(
                        subtitle_path,
                        source_path,
                    )
                elif target == 'all':
                    candidates = self._build_subtitle_filter_candidates(
                        subtitle_name,
                        source_name,
                        display_name,
                        display_source_name,
                        source_name_raw,
                        source_name_clean,
                        subtitle_path,
                        source_path,
                    )
                else:
                    candidates = self._build_subtitle_filter_candidates(
                        subtitle_name,
                        source_name,
                        display_name,
                        display_source_name,
                        source_name_raw,
                        source_name_clean,
                    )

                try:
                    if any(candidate and re.search(pattern, candidate, re.IGNORECASE) for candidate in candidates):
                        logger.info('[RJ字幕] 字幕候选被过滤规则[%s]排除: %s', rule_name, subtitle_name)
                        excluded = True
                        excluded_count += 1
                        break
                except re.error as exc:
                    logger.warning('[RJ字幕] 跳过无效过滤规则 %s: %s', rule_name, exc)

            if not excluded:
                filtered.append(normalized)

        if excluded_count:
            logger.info('[RJ字幕] 过滤规则排除了 %s 个字幕候选，保留 %s 个', excluded_count, len(filtered))
        logger.info(
            '[RJ字幕] 字幕过滤执行完成: 规则=%s 候选=%s 排除=%s 保留=%s',
            len(active_rules),
            len(subtitle_files),
            excluded_count,
            len(filtered),
        )
        return filtered

    def _subtitle_download_group_key(self, subtitle: Dict) -> Tuple[str, str]:
        normalized = self._normalize_subtitle_file(subtitle)
        track_number = normalized.get('track_number')
        relative_path = normalized.get('relative_path') or normalized.get('path') or normalized.get('name') or ''
        path_identity = self._normalize_identity_path(str(relative_path))
        normalized_name = normalized.get('normalized_name') or self._normalize_name(normalized.get('base_name') or '')
        identity = path_identity or (
            f"track:{track_number}" if track_number is not None else normalized_name or (normalized.get('base_name') or '').lower()
        )
        return normalized.get('ext') or '', identity

    def _dedupe_subtitle_candidates_for_download(self, subtitle_files: List[Dict], audio_files: List[Any]) -> List[Dict]:
        preferred_audio_exts = self._preferred_subtitle_source_audio_exts(audio_files)

        deduped: Dict[Tuple[str, str], Dict] = {}
        for subtitle in subtitle_files:
            normalized = self._normalize_subtitle_file(subtitle)
            dedupe_key = self._subtitle_download_group_key(normalized)
            deduped[dedupe_key] = self._pick_download_candidate(
                deduped.get(dedupe_key),
                normalized,
                preferred_audio_exts,
            )

        return sorted(deduped.values(), key=lambda item: item.get('name') or '')

    def _read_subtitle_text_for_fingerprint(self, file_path: str) -> str:
        data = Path(file_path).read_bytes()
        if not data:
            return ''

        for encoding in ('utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'gb18030', 'shift_jis'):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue

        return data.decode('utf-8', errors='ignore')

    def _normalize_subtitle_text_lines(self, content: str, ext: str) -> List[str]:
        normalized_lines: List[str] = []
        in_vtt_note_block = False

        for raw_line in content.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = raw_line.lstrip('\ufeff').strip()
            if not line:
                if ext == '.vtt':
                    in_vtt_note_block = False
                continue

            if ext == '.vtt':
                upper_line = line.upper()
                if upper_line == 'WEBVTT' or upper_line.startswith('STYLE') or upper_line.startswith('REGION') or upper_line.startswith('X-TIMESTAMP-MAP='):
                    continue
                if upper_line.startswith('NOTE'):
                    in_vtt_note_block = True
                    continue
                if in_vtt_note_block or '-->' in line:
                    continue
            elif ext == '.srt':
                if line.isdigit() or '-->' in line:
                    continue
            elif ext == '.lrc':
                if re.match(r'^\[[a-zA-Z]{2,16}:.*\]$', line):
                    continue
                line = re.sub(r'(?:\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\])+', '', line).strip()
                if not line:
                    continue
            elif ext in {'.ass', '.ssa'}:
                if not line.lower().startswith('dialogue:'):
                    continue
                payload = line.split(':', 1)[1].strip()
                segments = payload.split(',', 9)
                line = segments[9] if len(segments) >= 10 else payload
                if not line:
                    continue

            line = line.replace('\\N', ' ').replace('\\n', ' ')
            line = re.sub(r'<[^>]+>', ' ', line)
            line = re.sub(r'\{[^}]+\}', ' ', line)
            line = re.sub(r'\s+', ' ', line).strip()
            if line:
                normalized_lines.append(line)

        return normalized_lines

    def _build_subtitle_content_fingerprint(self, subtitle: Dict) -> Dict:
        normalized = self._normalize_subtitle_file(subtitle)
        file_path = str(normalized.get('path') or '')
        ext = str(normalized.get('ext') or '').lower()
        if not file_path or not os.path.exists(file_path):
            return {
                'content_fingerprint': None,
                'content_line_count': 0,
                'content_char_count': 0,
            }

        try:
            content = self._read_subtitle_text_for_fingerprint(file_path)
            normalized_content = content.replace('\r\n', '\n').replace('\r', '\n').strip()
            text_lines = self._normalize_subtitle_text_lines(normalized_content, ext)
            canonical_text = '\n'.join(text_lines) if text_lines else normalized_content
            canonical_text = canonical_text.strip()
            if not canonical_text:
                return {
                    'content_fingerprint': None,
                    'content_line_count': 0,
                    'content_char_count': 0,
                }
            return {
                'content_fingerprint': hashlib.sha1(canonical_text.encode('utf-8', errors='ignore')).hexdigest(),
                'content_line_count': len(text_lines) if text_lines else len([line for line in normalized_content.split('\n') if line.strip()]),
                'content_char_count': len(canonical_text),
            }
        except Exception as exc:
            logger.warning('[RJ字幕] 计算字幕内容指纹失败 %s: %s', file_path, exc)
            return {
                'content_fingerprint': None,
                'content_line_count': 0,
                'content_char_count': 0,
            }

    def _dedupe_downloaded_subtitles_by_content(
        self,
        downloaded_files: List[Dict],
        audio_files: List[Any],
    ) -> Tuple[List[Dict], List[Dict]]:
        if len(downloaded_files) <= 1:
            return downloaded_files, []

        preferred_audio_exts = self._preferred_subtitle_source_audio_exts(audio_files)
        retained: Dict[Tuple[str, str], Dict] = {}
        deduped_records: List[Dict] = []
        grouped_by_name: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)

        for subtitle in downloaded_files:
            normalized = self._normalize_subtitle_file(subtitle)
            subtitle_name_key = str(normalized.get('name') or '').strip().lower()
            grouped_by_name[(normalized.get('ext') or '', subtitle_name_key)].append(normalized)

        for name_key, group_items in grouped_by_name.items():
            if len(group_items) == 1:
                item = group_items[0]
                unique_key = str(item.get('path') or item.get('name') or uuid.uuid4().hex)
                retained[(item.get('ext') or '', unique_key)] = item
                continue

            for normalized in group_items:
                fingerprint_info = self._build_subtitle_content_fingerprint(normalized)
                normalized.update(fingerprint_info)

                fingerprint = normalized.get('content_fingerprint')
                if not fingerprint:
                    unique_key = str(normalized.get('path') or normalized.get('name') or uuid.uuid4().hex)
                    retained[(normalized.get('ext') or '', unique_key)] = normalized
                    continue

                dedupe_key = (name_key[0], fingerprint, name_key[1])
                existing = retained.get(dedupe_key)
                if existing is None:
                    retained[dedupe_key] = normalized
                    continue

                kept = self._pick_download_candidate(existing, normalized, preferred_audio_exts)
                dropped = normalized if kept is existing else existing
                retained[dedupe_key] = kept
                deduped_records.append({
                    'kept_name': kept.get('display_name') or kept.get('name') or '',
                    'dropped_name': dropped.get('display_name') or dropped.get('name') or '',
                    'kept_source_name': kept.get('source_name') or kept.get('name') or '',
                    'dropped_source_name': dropped.get('source_name') or dropped.get('name') or '',
                    'ext': kept.get('ext') or '',
                    'fingerprint': fingerprint,
                    'line_count': int(kept.get('content_line_count') or dropped.get('content_line_count') or 0),
                    'char_count': int(kept.get('content_char_count') or dropped.get('content_char_count') or 0),
                })

        deduped_files = sorted(
            retained.values(),
            key=lambda item: (
                str(item.get('display_name') or item.get('name') or ''),
                str(item.get('path') or ''),
            ),
        )
        return deduped_files, deduped_records

    def _prune_temp_subtitle_files(
        self,
        temp_dir: str,
        retained_files: List[Dict],
    ) -> None:
        retained_paths = {
            os.path.abspath(str(item.get('path') or ''))
            for item in retained_files
            if str(item.get('path') or '').strip()
        }
        if not retained_paths or not temp_dir or not os.path.isdir(temp_dir):
            return

        for root, _dirs, files in os.walk(temp_dir, topdown=False):
            for file_name in files:
                if os.path.splitext(file_name)[1].lower() not in self.SUBTITLE_EXTENSIONS:
                    continue
                file_path = os.path.abspath(os.path.join(root, file_name))
                if file_path in retained_paths:
                    continue
                try:
                    os.remove(file_path)
                except FileNotFoundError:
                    continue
            if os.path.abspath(root) == os.path.abspath(temp_dir):
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                continue

    def match_subtitles_to_audio(
        self,
        audio_files: List[Any],
        subtitle_files: List[Dict],
        enable_metadata_match: bool = True,
        naming_strategy: str = 'audio',
    ) -> Dict:
        """将下载的字幕匹配到本地音频"""
        resolved_naming_strategy = self._resolve_naming_strategy(naming_strategy)
        audio_index = self._build_audio_index(audio_files, enable_metadata_match=enable_metadata_match)
        subtitle_groups = self._group_subtitles(subtitle_files)
        used_audio = set()
        grouped_matches = []
        remaining_groups = []

        exact_map = {audio['base_name'].lower(): audio for audio in audio_index}
        normalized_map = {audio['normalized_name']: audio for audio in audio_index if audio['normalized_name']}
        number_map = {audio['track_number']: audio for audio in audio_index if audio['track_number'] is not None}

        def can_use(audio):
            return audio and audio['path'] not in used_audio

        for group in subtitle_groups:
            subtitle_base_lower = group['base_name'].lower()
            audio = exact_map.get(subtitle_base_lower)
            if can_use(audio):
                grouped_matches.append((group, audio, '完全匹配', 100))
                used_audio.add(audio['path'])
                continue

            track_number = group['track_number']
            if track_number is not None:
                audio = number_map.get(track_number)
                if can_use(audio):
                    grouped_matches.append((group, audio, f'序号匹配({track_number})', 95))
                    used_audio.add(audio['path'])
                    continue

            if enable_metadata_match:
                matched_audio = None
                for audio in audio_index:
                    if not can_use(audio):
                        continue
                    meta = audio.get('metadata') or {}
                    if track_number is not None and meta.get('track_number') == track_number:
                        matched_audio = (audio, f'metadata序号({track_number})', 88)
                        break
                    if group['normalized_name'] and meta.get('normalized_title'):
                        meta_title = meta['normalized_title']
                        if meta_title == group['normalized_name'] or group['normalized_name'] in meta_title or meta_title in group['normalized_name']:
                            matched_audio = (audio, 'metadata标题匹配', 84)
                            break

                if matched_audio:
                    grouped_matches.append((group, matched_audio[0], matched_audio[1], matched_audio[2]))
                    used_audio.add(matched_audio[0]['path'])
                    continue

            audio = normalized_map.get(group['normalized_name'])
            if can_use(audio):
                grouped_matches.append((group, audio, '规范化匹配', 80))
                used_audio.add(audio['path'])
                continue

            remaining_groups.append(group)

        ordered_remaining_audio = [audio for audio in audio_index if audio['path'] not in used_audio]
        for index, group in enumerate(remaining_groups):
            if index >= len(ordered_remaining_audio):
                break
            audio = ordered_remaining_audio[index]
            grouped_matches.append((group, audio, '顺序匹配', 70))
            used_audio.add(audio['path'])

        matched_subtitles = []
        matched_group_names = set()
        for group, audio, match_type, score in grouped_matches:
            matched_group_names.add(group['base_name'])
            for subtitle in group['files']:
                ext = subtitle['ext']
                subtitle_base = subtitle.get('base_name') or os.path.splitext(subtitle['name'])[0]
                output_base = audio['base_name'] if resolved_naming_strategy == 'audio' else subtitle_base
                matched_subtitles.append({
                    'audio_path': audio['path'],
                    'audio_name': audio.get('display_name') or os.path.basename(audio['path']),
                    'subtitle_path': subtitle['path'],
                    'subtitle_name': subtitle['name'],
                    'output_subtitle_name': f"{output_base}{ext}",
                    'match_type': match_type,
                    'match_score': score,
                })

        unmatched_audio = [
            audio.get('display_name') or os.path.basename(audio['path'])
            for audio in audio_index
            if audio['path'] not in used_audio
        ]
        unmatched_subtitles = [
            subtitle['name']
            for group in subtitle_groups
            if group['base_name'] not in matched_group_names
            for subtitle in group['files']
        ]

        return {
            'matches': matched_subtitles,
            'matched_group_count': len(grouped_matches),
            'matched_subtitle_count': len(matched_subtitles),
            'unmatched_audio': unmatched_audio,
            'unmatched_subtitles': unmatched_subtitles,
        }

    async def _maybe_apply_ai_auto_match(
        self,
        *,
        audio_files: List[Any],
        subtitle_files: List[Dict],
        base_match_result: Dict,
        enable_metadata_match: bool,
        naming_strategy: str,
        ai_match_mode: Optional[str] = None,
        ai_confidence_threshold: Optional[int] = None,
        task_id: str = "",
        rjcode: str = "",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        from ..config.settings import get_config
        from .ai_subtitle_match_service import AI_ACTIVE_MODES, get_ai_subtitle_match_service, normalize_ai_match_mode

        config = get_config()
        ai_config = getattr(config, 'ai_subtitle_matching', None)
        mode = normalize_ai_match_mode(ai_match_mode or 'rule_ai_auto')
        if mode not in AI_ACTIVE_MODES:
            return {
                'used': False,
                'auto_safe': False,
                'status': 'skipped',
                'match_result': base_match_result,
                'metadata': {
                    'ai_match_mode': mode,
                    'ai_match_status': 'skipped',
                    'ai_auto_applied': False,
                },
            }

        if progress_callback:
            progress_callback(86, 'AI 分析字幕配对')

        audio_index = self._build_audio_index(audio_files, enable_metadata_match=enable_metadata_match)
        subtitle_groups = self._group_subtitles(subtitle_files)
        return await get_ai_subtitle_match_service().build_auto_match_result(
            config=ai_config,
            audio_index=audio_index,
            subtitle_groups=subtitle_groups,
            base_match_result=base_match_result,
            mode=mode,
            naming_strategy=self._resolve_naming_strategy(naming_strategy),
            threshold=ai_confidence_threshold,
            task_id=task_id,
            rjcode=rjcode,
        )

    def _is_synology_error_code(self, exc: Exception, code: int) -> bool:
        message = str(exc)
        patterns = [
            rf'代码\s*{code}\b',
            rf'"code"\s*:\s*{code}\b',
            rf"'code'\s*:\s*{code}\b",
        ]
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)

    def _is_synology_error_codes(self, exc: Exception, *codes: int) -> bool:
        return any(self._is_synology_error_code(exc, code) for code in codes)

    def _resolve_remote_info_item_path(self, info: Dict, fallback_path: str) -> str:
        files = info.get('files') or []
        item = files[0] if files else {}
        path = item.get('path') or item.get('real_path') or fallback_path
        normalized = str(PurePosixPath(path if str(path).startswith('/') else f'/{path}'))
        return normalized

    async def _ensure_remote_subtitle_dir(self, client, folder_path: str) -> str:
        normalized_folder = str(PurePosixPath(folder_path if folder_path.startswith('/') else f'/{folder_path}'))
        folder_info = await client.stat(normalized_folder)
        canonical_folder = self._resolve_remote_info_item_path(folder_info, normalized_folder)
        subtitle_dir = str(PurePosixPath(canonical_folder) / 'subtitles')

        try:
            subtitle_info = await client.stat(subtitle_dir)
            return self._resolve_remote_info_item_path(subtitle_info, subtitle_dir)
        except Exception as exc:
            if not self._is_synology_error_codes(exc, 118, 119, 408):
                raise

        try:
            await client.create_folder(canonical_folder, 'subtitles')
        except Exception as exc:
            if self._is_synology_error_code(exc, 117):
                return subtitle_dir
            if self._is_synology_error_codes(exc, 119, 408):
                try:
                    subtitle_info = await client.stat(subtitle_dir)
                    return self._resolve_remote_info_item_path(subtitle_info, subtitle_dir)
                except Exception:
                    pass
                raise
            raise
        try:
            subtitle_info = await client.stat(subtitle_dir)
            return self._resolve_remote_info_item_path(subtitle_info, subtitle_dir)
        except Exception as exc:
            if self._is_synology_error_codes(exc, 118, 119, 408):
                return subtitle_dir
            raise

    def _annotate_download_display_names(self, downloaded_files: List[Dict], match_result: Optional[Dict]) -> None:
        if not downloaded_files:
            return

        display_name_by_path = {}
        display_name_by_name = {}
        for match in (match_result or {}).get('matches', []):
            subtitle_path = str(match.get('subtitle_path') or '')
            subtitle_name = str(match.get('subtitle_name') or '')
            output_name = str(match.get('output_subtitle_name') or '')
            if not output_name:
                continue
            if subtitle_path:
                display_name_by_path[subtitle_path] = output_name
            if subtitle_name and subtitle_name not in display_name_by_name:
                display_name_by_name[subtitle_name] = output_name

        for item in downloaded_files:
            subtitle_path = str(item.get('path') or '')
            subtitle_name = str(item.get('name') or '')
            display_name = display_name_by_path.get(subtitle_path) or display_name_by_name.get(subtitle_name)
            if display_name:
                item['display_name'] = display_name

    def _validate_ai_auto_output_conflicts(
        self,
        match_result: Optional[Dict],
        existing_names: set[str],
        overwrite: bool,
    ) -> List[str]:
        if overwrite:
            return []
        conflicts: List[str] = []
        for match in (match_result or {}).get('matches', []):
            output_name = os.path.basename(str(match.get('output_subtitle_name') or '')).strip()
            if not output_name:
                continue
            equivalent_names = self._find_equivalent_subtitle_names(existing_names, output_name)
            if output_name in existing_names or equivalent_names:
                conflicts.append(output_name)
        return sorted(set(conflicts))

    def _downgrade_ai_auto_to_manual(self, ai_metadata: Dict, match_result: Dict, reason: str) -> Dict:
        metadata = dict(ai_metadata or {})
        errors = list((match_result or {}).get('ai_validation_errors') or [])
        if reason and reason not in errors:
            errors.append(reason)
        if isinstance(match_result, dict):
            match_result['ai_validation_errors'] = errors
        metadata.update({
            'ai_match_status': 'awaiting_manual',
            'ai_auto_applied': False,
            'ai_match_result': match_result,
        })
        return metadata

    async def _remote_subtitle_exists(self, client, subtitle_dir: str, file_name: str) -> bool:
        try:
            return file_name in await self._get_remote_existing_subtitle_names(client, subtitle_dir)
        except Exception:
            return False

    def _build_remote_upload_temp_name(self, index: int, output_name: str) -> str:
        ext = os.path.splitext(output_name)[1].lower() or '.vtt'
        return f"__kikoerumanager_upload_{index:04d}_{uuid.uuid4().hex[:8]}{ext}"

    def _build_raw_subtitle_output_name(self, subtitle: Dict, used_names: set[str], existing_names: set[str], overwrite: bool) -> Optional[str]:
        normalized = self._normalize_subtitle_file(subtitle)
        base_name = str(normalized.get('base_name') or '').strip()
        ext = str(normalized.get('ext') or os.path.splitext(str(normalized.get('name') or ''))[1].lower() or '.vtt')
        desired_name = f'{base_name}{ext}' if base_name else ''
        desired_name = os.path.basename(desired_name or str(normalized.get('name') or ''))
        desired_name = re.sub(r'[<>:"|?*]', '_', desired_name).strip()
        if not desired_name:
            desired_name = f"subtitle_{len(used_names) + 1:03d}.vtt"

        if desired_name in existing_names and not overwrite:
            equivalent_names = self._find_equivalent_subtitle_names(existing_names, desired_name)
            return desired_name if equivalent_names else None

        candidate = desired_name
        base, ext = os.path.splitext(desired_name)
        suffix = 2
        while candidate in used_names:
            candidate = f"{base}__{suffix}{ext}"
            suffix += 1
        return candidate

    def _preview_raw_subtitle_output_name(self, subtitle: Dict) -> str:
        normalized = self._normalize_subtitle_file(subtitle)
        base_name = str(normalized.get('base_name') or '').strip()
        ext = str(normalized.get('ext') or os.path.splitext(str(normalized.get('name') or ''))[1].lower() or '.vtt')
        desired_name = os.path.basename(f'{base_name}{ext}' if base_name else str(normalized.get('name') or ''))
        desired_name = re.sub(r'[<>:"|?*]', '_', desired_name).strip()
        return desired_name or 'subtitle.vtt'

    def _subtitle_name_identity(self, file_name: str) -> Tuple[str, str]:
        normalized = self._normalize_subtitle_file({'name': file_name})
        return (
            str(normalized.get('base_name') or '').lower(),
            str(normalized.get('ext') or '').lower(),
        )

    def _find_equivalent_subtitle_names(self, names: set[str], target_name: str) -> List[str]:
        target_identity = self._subtitle_name_identity(target_name)
        return sorted(
            [
                name
                for name in names
                if name != target_name and self._subtitle_name_identity(name) == target_identity
            ]
        )

    def _list_local_existing_subtitle_names(self, subtitle_dir: Path) -> set[str]:
        if not subtitle_dir.exists():
            return set()
        return {item.name for item in subtitle_dir.iterdir() if item.is_file()}

    async def _get_remote_existing_subtitle_names(self, client, subtitle_dir: str) -> set[str]:
        offset = 0
        limit = 500
        names: set[str] = set()
        try:
            while True:
                try:
                    data = await client.list(subtitle_dir, offset=offset, limit=limit, sort_by='name', sort_direction='asc')
                except Exception as exc:
                    if self._is_synology_error_codes(exc, 118, 119, 408):
                        logger.warning('[RJ字幕] 读取远程已有字幕失败，按空结果继续: %s', exc)
                        return names
                    raise
                raw_items = data.get('files') or []
                for item in raw_items:
                    if item.get('isdir', False):
                        continue
                    name = item.get('name') or ''
                    if os.path.splitext(name)[1].lower() in self.SUBTITLE_EXTENSIONS:
                        names.add(name)
                total = int(data.get('total', len(raw_items)) or len(raw_items))
                offset += len(raw_items)
                if not raw_items or offset >= total:
                    break
        except Exception as exc:
            logger.warning('[RJ字幕] 获取远程已有字幕列表异常，按空结果继续: %s', exc)
            return names
        return names

    async def _cleanup_stranded_upload_temps(self, client, subtitle_dir: str, existing_names: set[str]) -> None:
        """清理上次写入中断遗留的临时上传文件（__kikoerumanager_upload_* 前缀），保证幂等。"""
        _TEMP_PREFIX = "__kikoerumanager_upload_"
        stranded = [name for name in existing_names if name.startswith(_TEMP_PREFIX)]
        for name in stranded:
            try:
                await client.delete(str(PurePosixPath(subtitle_dir) / name))
                existing_names.discard(name)
                logger.info('[RJ字幕] 已清理遗留临时上传文件: %s', name)
            except Exception as _ce:
                logger.debug('[RJ字幕] 清理遗留临时文件失败（忽略）: %s error=%s', name, _ce)

    async def clear_existing_subtitles_for_folder(
        self,
        folder_path: str,
        library_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        subtitle_dir = ''
        deleted_subtitles = 0

        if library_id:
            from .library_manager import SynologyFileStationClient, get_library_manager

            manager = get_library_manager()
            library = manager.get_library_definition(library_id)
            if library.type == 'synology_filestation':
                if not library.synology:
                    raise RuntimeError('远程库存未配置群晖连接参数')
                folder_info = await manager.folder_contents(library_id, folder_path, prefer_index=False)
                remote_items = folder_info.get('items') or []
                deleted_subtitles = self._count_remote_existing_subtitles(remote_items)
                subtitle_dir = manager._normalize_remote_path(str(PurePosixPath(folder_path) / 'subtitles'))
                client = manager.get_cached_synology_client(library.synology)
                try:
                    await client.delete(subtitle_dir)
                except Exception as exc:
                    if not self._is_synology_error_codes(exc, 118, 119, 408):
                        raise
                return {
                    'subtitle_dir': subtitle_dir,
                    'deleted_subtitles': deleted_subtitles,
                    'deleted': deleted_subtitles > 0,
                }

        folder = Path(folder_path)
        subtitle_path = folder / 'subtitles'
        subtitle_dir = str(subtitle_path)
        deleted_subtitles = self._count_existing_subtitles(folder)
        if subtitle_path.exists():
            await asyncio.to_thread(shutil.rmtree, subtitle_path)
        return {
            'subtitle_dir': subtitle_dir,
            'deleted_subtitles': deleted_subtitles,
            'deleted': deleted_subtitles > 0,
        }

    def _build_written_subtitle_record(self, item: Dict, output_name: str, match_type: str = '原始抓取') -> Dict:
        return {
            'subtitle_name': item.get('source_name') or item.get('name') or output_name,
            'output_name': output_name,
            'match_type': match_type,
            'match_score': 0,
        }

    def _build_written_match_record(self, match: Dict) -> Dict:
        return {
            'audio_name': match.get('audio_name') or '',
            'subtitle_name': match.get('subtitle_name') or match.get('output_subtitle_name') or '',
            'output_name': match.get('output_subtitle_name') or '',
            'match_type': match.get('match_type') or 'AI自动配对',
            'match_score': int(match.get('match_score') or match.get('ai_confidence') or 0),
        }

    def _write_local_matched_subtitles(
        self,
        folder: Path,
        match_result: Dict,
        overwrite: bool,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[str, List[Dict], List[str], List[str]]:
        subtitle_dir = folder / 'subtitles'
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        existing_names = self._list_local_existing_subtitle_names(subtitle_dir)
        used_names: set[str] = set()
        written_files: List[Dict] = []
        skipped_files: List[str] = []
        write_errors: List[str] = []
        matches = list(match_result.get('matches') or [])
        total_matches = max(len(matches), 1)

        for index, match in enumerate(matches, start=1):
            if should_cancel and should_cancel():
                raise asyncio.CancelledError()
            output_name = os.path.basename(str(match.get('output_subtitle_name') or '')).strip()
            source_path = str(match.get('subtitle_path') or '')
            if not output_name or not source_path:
                write_errors.append(f"{output_name or source_path or 'unknown'}: 缺少字幕源或输出名")
                continue
            key = output_name.lower()
            if key in used_names:
                write_errors.append(f"{output_name}: 输出名重复")
                continue
            used_names.add(key)
            destination = subtitle_dir / output_name
            if progress_callback:
                progress = 92 + int((index - 1) / total_matches * 6)
                progress_callback(progress, f"写入匹配字幕 {index}/{total_matches}: {output_name}")
            try:
                equivalent_names = self._find_equivalent_subtitle_names(existing_names, output_name)
                if overwrite:
                    cleanup_names = []
                    if output_name in existing_names:
                        cleanup_names.append(output_name)
                    cleanup_names.extend(equivalent_names)
                    for name in cleanup_names:
                        target_path = subtitle_dir / name
                        if target_path.exists():
                            target_path.unlink()
                        existing_names.discard(name)
                elif output_name in existing_names:
                    skipped_files.append(output_name)
                    continue
                elif equivalent_names:
                    skipped_files.append(output_name)
                    continue
                shutil.copy2(source_path, destination)
                existing_names.add(output_name)
                written_files.append(self._build_written_match_record(match))
            except Exception as exc:
                write_errors.append(f"{output_name}: {exc}")

        if progress_callback:
            progress_callback(98, f"匹配字幕写入完成，写入 {len(written_files)}，跳过 {len(skipped_files)}")
        return str(subtitle_dir), written_files, skipped_files, write_errors

    async def _migrate_remote_equivalent_subtitles(
        self,
        client,
        subtitle_dir: str,
        output_name: str,
        existing_names: set[str],
        overwrite: bool,
    ) -> bool:
        equivalent_names = self._find_equivalent_subtitle_names(existing_names, output_name)

        if overwrite:
            cleanup_names = []
            if output_name in existing_names:
                cleanup_names.append(output_name)
            cleanup_names.extend(equivalent_names)
            for name in cleanup_names:
                try:
                    await client.delete(str(PurePosixPath(subtitle_dir) / name))
                except Exception as exc:
                    if not self._is_synology_error_codes(exc, 118, 119, 408):
                        raise
                existing_names.discard(name)
            return False

        if output_name in existing_names:
            for legacy_name in equivalent_names:
                try:
                    await client.delete(str(PurePosixPath(subtitle_dir) / legacy_name))
                except Exception as exc:
                    if not self._is_synology_error_codes(exc, 118, 119, 408):
                        raise
                existing_names.discard(legacy_name)
            return True

        if not equivalent_names:
            return False

        primary_name = equivalent_names[0]
        await client.rename(str(PurePosixPath(subtitle_dir) / primary_name), output_name)
        existing_names.discard(primary_name)
        existing_names.add(output_name)
        for legacy_name in equivalent_names[1:]:
            try:
                await client.delete(str(PurePosixPath(subtitle_dir) / legacy_name))
            except Exception as exc:
                if not self._is_synology_error_codes(exc, 118, 119, 408):
                    raise
            existing_names.discard(legacy_name)
        return True

    def _write_local_downloaded_subtitles(
        self,
        folder: Path,
        downloaded_files: List[Dict],
        overwrite: bool,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[str, List[Dict], List[str], List[str]]:
        subtitle_dir = folder / 'subtitles'
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        existing_names = self._list_local_existing_subtitle_names(subtitle_dir)
        used_names: set[str] = set()
        written_files: List[Dict] = []
        skipped_files: List[str] = []
        write_errors: List[str] = []
        total_files = max(len(downloaded_files), 1)

        for index, item in enumerate(downloaded_files, start=1):
            if should_cancel and should_cancel():
                raise asyncio.CancelledError()
            output_name = self._build_raw_subtitle_output_name(item, used_names, existing_names, overwrite)
            if not output_name:
                skipped_files.append(os.path.basename(str(item.get('name') or '')))
                continue
            used_names.add(output_name)
            destination = subtitle_dir / output_name
            if progress_callback:
                progress = 72 + int((index - 1) / total_files * 24)
                progress_callback(progress, f"写入原始字幕 {index}/{total_files}: {output_name}")
            try:
                equivalent_names = self._find_equivalent_subtitle_names(existing_names, output_name)
                if overwrite:
                    cleanup_names = []
                    if output_name in existing_names:
                        cleanup_names.append(output_name)
                    cleanup_names.extend(equivalent_names)
                    for name in cleanup_names:
                        target_path = subtitle_dir / name
                        if target_path.exists():
                            target_path.unlink()
                        existing_names.discard(name)
                elif output_name in existing_names:
                    for legacy_name in equivalent_names:
                        legacy_path = subtitle_dir / legacy_name
                        if legacy_path.exists():
                            legacy_path.unlink()
                        existing_names.discard(legacy_name)
                    skipped_files.append(output_name)
                    continue
                elif equivalent_names:
                    primary_name = equivalent_names[0]
                    primary_path = subtitle_dir / primary_name
                    if primary_path.exists():
                        primary_path.rename(destination)
                    existing_names.discard(primary_name)
                    existing_names.add(output_name)
                    for legacy_name in equivalent_names[1:]:
                        legacy_path = subtitle_dir / legacy_name
                        if legacy_path.exists():
                            legacy_path.unlink()
                        existing_names.discard(legacy_name)
                    item['output_name'] = output_name
                    item['display_name'] = output_name
                    written_files.append(self._build_written_subtitle_record(item, output_name, '旧名迁移'))
                    continue
                shutil.copy2(item['path'], destination)
                existing_names.add(output_name)
                item['output_name'] = output_name
                item['display_name'] = output_name
                written_files.append({
                    'subtitle_name': item.get('name') or output_name,
                    'output_name': output_name,
                    'match_type': '原始抓取',
                    'match_score': 0,
                })
            except Exception as exc:
                write_errors.append(f"{output_name}: {exc}")

        if progress_callback:
            progress_callback(98, f"原始字幕写入完成，保留 {len(written_files)}，跳过 {len(skipped_files)}")
        return str(subtitle_dir), written_files, skipped_files, write_errors

    async def _write_remote_downloaded_subtitles(
        self,
        library_id: str,
        folder_path: str,
        downloaded_files: List[Dict],
        overwrite: bool,
        temp_dir: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[str, List[Dict], List[str], List[str]]:
        from .library_manager import SynologyFileStationClient, get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if not library.synology:
            raise RuntimeError('远程库存未配置群晖连接参数')

        client = manager.get_cached_synology_client(library.synology)
        subtitle_dir = await self._ensure_remote_subtitle_dir(client, folder_path)
        existing_names = await self._get_remote_existing_subtitle_names(client, subtitle_dir)
        # 清理上次中断遗留的临时上传文件，保证写入幂等
        await self._cleanup_stranded_upload_temps(client, subtitle_dir, existing_names)
        used_names: set[str] = set()
        written_files: List[Dict] = []
        skipped_files: List[str] = []
        write_errors: List[str] = []
        total_files = max(len(downloaded_files), 1)

        upload_stage_dir = os.path.join(temp_dir, '_remote_upload_raw')
        os.makedirs(upload_stage_dir, exist_ok=True)

        # --- Phase 1（串行）: 预计算名称 + 旧名迁移，保证 existing_names/used_names 状态一致 ---
        work_items: List[Dict] = []
        for index, item in enumerate(downloaded_files, start=1):
            if should_cancel and should_cancel():
                raise asyncio.CancelledError()
            output_name = self._build_raw_subtitle_output_name(item, used_names, existing_names, overwrite)
            if not output_name:
                skipped_files.append(os.path.basename(str(item.get('name') or '')))
                continue
            used_names.add(output_name)
            temp_remote_name = self._build_remote_upload_temp_name(index, output_name)
            temp_remote_path = str(PurePosixPath(subtitle_dir) / temp_remote_name)
            final_remote_path = str(PurePosixPath(subtitle_dir) / output_name)
            staged_path = os.path.join(upload_stage_dir, output_name)
            if progress_callback:
                progress = 72 + int((index - 1) / total_files * 12)
                progress_callback(progress, f"预处理字幕 {index}/{total_files}: {output_name}")
            try:
                migrated = await self._migrate_remote_equivalent_subtitles(
                    client=client,
                    subtitle_dir=subtitle_dir,
                    output_name=output_name,
                    existing_names=existing_names,
                    overwrite=overwrite,
                )
                if migrated:
                    item['output_name'] = output_name
                    item['display_name'] = output_name
                    written_files.append({
                        'subtitle_name': item.get('source_name') or item.get('name') or output_name,
                        'output_name': output_name,
                        'match_type': '旧名迁移',
                        'match_score': 0,
                    })
                else:
                    work_items.append({
                        'item': item,
                        'output_name': output_name,
                        'temp_remote_name': temp_remote_name,
                        'temp_remote_path': temp_remote_path,
                        'final_remote_path': final_remote_path,
                        'staged_path': staged_path,
                    })
            except Exception as exc:
                write_errors.append(f"{output_name}: {exc}")

        # --- Phase 2（串行上传）: 群晖写同一 subtitles/ 目录时存在目录锁，并发会导致 sock_read 超时，改为串行 ---
        upload_count = len(work_items)
        completed_uploads = 0
        _upload_semaphore = asyncio.Semaphore(1)

        async def do_upload(work: dict):
            nonlocal completed_uploads
            w_item = work['item']
            output_name = work['output_name']
            temp_remote_name = work['temp_remote_name']
            temp_remote_path = work['temp_remote_path']
            final_remote_path = work['final_remote_path']
            staged_path = work['staged_path']
            async with _upload_semaphore:
                if progress_callback:
                    progress = 84 + int(completed_uploads / max(upload_count, 1) * 14)
                    progress_callback(progress, f"上传字幕: {output_name}")
                try:
                    await asyncio.to_thread(shutil.copy2, w_item['path'], staged_path)
                    await client.upload_file(subtitle_dir, staged_path, overwrite=True, remote_name=temp_remote_name)
                    if overwrite and output_name in existing_names:
                        try:
                            await client.delete(final_remote_path)
                        except Exception as exc:
                            if not self._is_synology_error_code(exc, 118):
                                raise
                    await client.rename(temp_remote_path, output_name)
                    existing_names.add(output_name)
                    w_item['output_name'] = output_name
                    w_item['display_name'] = output_name
                    written_files.append({
                        'subtitle_name': w_item.get('name') or output_name,
                        'output_name': output_name,
                        'match_type': '原始抓取',
                        'match_score': 0,
                    })
                except Exception as exc:
                    if await self._remote_subtitle_exists(client, subtitle_dir, output_name):
                        existing_names.add(output_name)
                        w_item['output_name'] = output_name
                        w_item['display_name'] = output_name
                        written_files.append({
                            'subtitle_name': w_item.get('name') or output_name,
                            'output_name': output_name,
                            'match_type': '原始抓取',
                            'match_score': 0,
                        })
                    else:
                        write_errors.append(f"{output_name}: {exc}")
                completed_uploads += 1

        await asyncio.gather(*[do_upload(work) for work in work_items])

        if progress_callback:
            progress_callback(98, f"原始字幕写入完成，保留 {len(written_files)}，跳过 {len(skipped_files)}")
        return subtitle_dir, written_files, skipped_files, write_errors

    async def import_subtitles_to_folder(
        self,
        *,
        folder_path: str,
        source_subtitles: List[Dict],
        library_id: Optional[str] = None,
        overwrite: Optional[bool] = None,
        use_filter_rules: Optional[bool] = None,
        subtitle_filter_rules: Optional[List[Dict]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict:
        """Import already-extracted subtitle files into an existing RJ folder."""
        from ..config.settings import get_config
        from .library_manager import get_library_manager

        config = get_config()
        overwrite = getattr(config.rj_subtitle, 'overwrite_existing', False) if overwrite is None else overwrite
        use_filter_rules = getattr(config.rj_subtitle, 'auto_import_use_filter_rules', True) if use_filter_rules is None else use_filter_rules
        if subtitle_filter_rules is None:
            subtitle_filter_rules = getattr(config.rj_subtitle, 'auto_import_filter_rules', []) or []

        normalized_subtitles = []
        for item in source_subtitles or []:
            normalized = self._normalize_subtitle_file(item)
            if normalized.get('ext') not in self.SUBTITLE_EXTENSIONS:
                continue
            normalized_subtitles.append(normalized)

        empty_match_result = {
            'matches': [],
            'matched_group_count': 0,
            'matched_subtitle_count': 0,
            'unmatched_audio': [],
            'unmatched_subtitles': [],
        }

        if not normalized_subtitles:
            return {
                'success': False,
                'error': '未检测到可导入的字幕文件',
                'download_files': [],
                'downloaded_count': 0,
                'content_deduped_count': 0,
                'content_deduped_files': [],
                'written_files': [],
                'skipped_files': [],
                'write_errors': [],
                'awaiting_manual_match': False,
                'existing_subtitle_count': 0,
                'subtitle_dir': '',
                'match_result': empty_match_result,
            }

        if use_filter_rules:
            normalized_subtitles = self._apply_subtitle_filter_rules(
                normalized_subtitles,
                subtitle_filter_rules or [],
            )

        if not normalized_subtitles:
            return {
                'success': False,
                'error': '字幕过滤后没有可导入的文件',
                'download_files': [],
                'downloaded_count': 0,
                'content_deduped_count': 0,
                'content_deduped_files': [],
                'written_files': [],
                'skipped_files': [],
                'write_errors': [],
                'awaiting_manual_match': False,
                'existing_subtitle_count': 0,
                'subtitle_dir': '',
                'match_result': empty_match_result,
            }

        if should_cancel and should_cancel():
            raise asyncio.CancelledError()

        if progress_callback:
            progress_callback(18, f"准备导入 {len(normalized_subtitles)} 个字幕文件")

        audio_items: List[Any]
        existing_subtitle_count = 0
        content_deduped_files: List[Dict] = []
        temp_dir: Optional[str] = None

        try:
            if library_id:
                manager = get_library_manager()
                library = manager.get_library_definition(library_id)
                if library.type != 'synology_filestation':
                    raise ValueError('指定库存不是远程库存')
                folder_info = await manager.folder_contents(library_id, folder_path, prefer_index=False)
                remote_items = folder_info.get('items') or []
                audio_items = self._collect_remote_audio_entries(remote_items)
                existing_subtitle_count = self._count_remote_existing_subtitles(remote_items)
                downloaded_files, content_deduped_files = self._dedupe_downloaded_subtitles_by_content(
                    normalized_subtitles,
                    audio_items,
                )
                if not downloaded_files:
                    return {
                        'success': False,
                        'error': '内容去重后没有可导入的字幕文件',
                        'download_files': [],
                        'downloaded_count': 0,
                        'content_deduped_count': len(content_deduped_files),
                        'content_deduped_files': content_deduped_files,
                        'written_files': [],
                        'skipped_files': [],
                        'write_errors': [],
                        'awaiting_manual_match': False,
                        'existing_subtitle_count': existing_subtitle_count,
                        'subtitle_dir': '',
                        'match_result': empty_match_result,
                    }
                temp_root = os.path.join(config.storage.temp_path, 'rj_subtitle_import')
                os.makedirs(temp_root, exist_ok=True)
                temp_dir = tempfile.mkdtemp(prefix='linked_import_', dir=temp_root)
                subtitle_dir, written_files, skipped_files, write_errors = await self._write_remote_downloaded_subtitles(
                    library_id=library_id,
                    folder_path=folder_path,
                    downloaded_files=downloaded_files,
                    overwrite=overwrite,
                    temp_dir=temp_dir,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
            else:
                folder = Path(folder_path)
                audio_items = self._collect_audio_files(folder)
                existing_subtitle_count = self._count_existing_subtitles(folder)
                downloaded_files, content_deduped_files = self._dedupe_downloaded_subtitles_by_content(
                    normalized_subtitles,
                    audio_items,
                )
                if not downloaded_files:
                    return {
                        'success': False,
                        'error': '内容去重后没有可导入的字幕文件',
                        'download_files': [],
                        'downloaded_count': 0,
                        'content_deduped_count': len(content_deduped_files),
                        'content_deduped_files': content_deduped_files,
                        'written_files': [],
                        'skipped_files': [],
                        'write_errors': [],
                        'awaiting_manual_match': False,
                        'existing_subtitle_count': existing_subtitle_count,
                        'subtitle_dir': '',
                        'match_result': empty_match_result,
                    }
                subtitle_dir, written_files, skipped_files, write_errors = self._write_local_downloaded_subtitles(
                    folder=folder,
                    downloaded_files=downloaded_files,
                    overwrite=overwrite,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )

            success = len(written_files) > 0
            awaiting_manual_match = success and bool(audio_items)
            match_result = {
                **empty_match_result,
                'unmatched_audio': [] if audio_items else ['目标目录未检测到音频文件'],
            }

            return {
                'success': success,
                'partial': bool(success and write_errors),
                'error': None if success else '未能导入任何字幕文件',
                'download_files': downloaded_files if success else [],
                'downloaded_count': len(downloaded_files) if success else 0,
                'content_deduped_count': len(content_deduped_files),
                'content_deduped_files': content_deduped_files,
                'written_files': written_files,
                'skipped_files': skipped_files,
                'write_errors': write_errors,
                'awaiting_manual_match': awaiting_manual_match,
                'existing_subtitle_count': existing_subtitle_count,
                'subtitle_dir': subtitle_dir,
                'match_result': match_result,
            }
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    async def _write_remote_subtitles(
        self,
        library_id: str,
        folder_path: str,
        match_result: Dict,
        overwrite: bool,
        temp_dir: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Tuple[str, List[Dict], List[str], List[str]]:
        from .library_manager import SynologyFileStationClient, get_library_manager

        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if not library.synology:
            raise RuntimeError('远程库存未配置群晖连接参数')

        client = manager.get_cached_synology_client(library.synology)
        subtitle_dir = await self._ensure_remote_subtitle_dir(client, folder_path)
        existing_names = await self._get_remote_existing_subtitle_names(client, subtitle_dir)
        # 清理上次中断遗留的临时上传文件，保证写入幂等
        await self._cleanup_stranded_upload_temps(client, subtitle_dir, existing_names)

        upload_stage_dir = os.path.join(temp_dir, '_remote_upload')
        os.makedirs(upload_stage_dir, exist_ok=True)

        written_files = []
        skipped_files = []
        write_errors = []
        total_matches = max(len(match_result['matches']), 1)

        # --- Phase 1（串行）: 预检跳过 / 构造任务列表（保持 existing_names 状态一致）---
        work_items: List[Dict] = []
        for index, match in enumerate(match_result['matches'], start=1):
            if should_cancel and should_cancel():
                raise asyncio.CancelledError()
            output_name = match['output_subtitle_name']
            if progress_callback:
                progress = 92 + int((index - 1) / total_matches * 3)
                progress_callback(progress, f"预处理字幕 {index}/{total_matches}: {output_name}")
            if output_name in existing_names and not overwrite:
                logger.info('[RJ字幕] 远程字幕已存在，跳过写入: %s', output_name)
                skipped_files.append(output_name)
                continue
            if overwrite:
                for legacy_name in {output_name, *self._find_equivalent_subtitle_names(existing_names, output_name)}:
                    if legacy_name not in existing_names:
                        continue
                    try:
                        await client.delete(str(PurePosixPath(subtitle_dir) / legacy_name))
                    except Exception as exc:
                        if not self._is_synology_error_codes(exc, 118, 119, 408):
                            raise
                    existing_names.discard(legacy_name)
            staged_path = os.path.join(upload_stage_dir, output_name)
            temp_remote_name = self._build_remote_upload_temp_name(index, output_name)
            temp_remote_path = str(PurePosixPath(subtitle_dir) / temp_remote_name)
            final_remote_path = str(PurePosixPath(subtitle_dir) / output_name)
            work_items.append({
                'match': match,
                'output_name': output_name,
                'staged_path': staged_path,
                'temp_remote_name': temp_remote_name,
                'temp_remote_path': temp_remote_path,
                'final_remote_path': final_remote_path,
            })

        # --- Phase 2（串行上传）: 群晖写同一 subtitles/ 目录时存在目录锁，并发会导致 sock_read 超时，改为串行 ---
        upload_count = len(work_items)
        completed_uploads = 0
        _upload_semaphore = asyncio.Semaphore(1)

        async def do_upload(work: dict):
            nonlocal completed_uploads
            match = work['match']
            output_name = work['output_name']
            staged_path = work['staged_path']
            temp_remote_name = work['temp_remote_name']
            temp_remote_path = work['temp_remote_path']
            final_remote_path = work['final_remote_path']
            async with _upload_semaphore:
                if progress_callback:
                    progress = 95 + int(completed_uploads / max(upload_count, 1) * 3)
                    progress_callback(progress, f"回写远程 subtitles: {output_name}")
                try:
                    await asyncio.to_thread(shutil.copy2, match['subtitle_path'], staged_path)
                    logger.info('[RJ字幕] 开始回写远程字幕 %s 临时名=%s', output_name, temp_remote_name)
                    await client.upload_file(subtitle_dir, staged_path, overwrite=True, remote_name=temp_remote_name)
                    if overwrite and output_name in existing_names:
                        try:
                            await client.delete(final_remote_path)
                        except Exception as exc:
                            if not self._is_synology_error_code(exc, 118):
                                raise
                    await client.rename(temp_remote_path, output_name)
                    existing_names.add(output_name)
                    written_files.append({
                        'audio_name': match['audio_name'],
                        'subtitle_name': match['subtitle_name'],
                        'output_name': output_name,
                        'match_type': match['match_type'],
                        'match_score': match['match_score'],
                    })
                except Exception as exc:
                    logger.warning('[RJ字幕] 远程字幕回写失败 %s: %s', output_name, exc)
                    if await self._remote_subtitle_exists(client, subtitle_dir, output_name):
                        existing_names.add(output_name)
                        written_files.append({
                            'audio_name': match['audio_name'],
                            'subtitle_name': match['subtitle_name'],
                            'output_name': output_name,
                            'match_type': match['match_type'],
                            'match_score': match['match_score'],
                        })
                    elif await self._remote_subtitle_exists(client, subtitle_dir, temp_remote_name):
                        try:
                            if overwrite and output_name in existing_names:
                                try:
                                    await client.delete(final_remote_path)
                                except Exception as delete_exc:
                                    if not self._is_synology_error_code(delete_exc, 118):
                                        raise
                            await client.rename(temp_remote_path, output_name)
                            existing_names.add(output_name)
                            written_files.append({
                                'audio_name': match['audio_name'],
                                'subtitle_name': match['subtitle_name'],
                                'output_name': output_name,
                                'match_type': match['match_type'],
                                'match_score': match['match_score'],
                            })
                        except Exception as rename_exc:
                            logger.warning('[RJ字幕] 临时远程字幕重命名失败 %s -> %s: %s', temp_remote_name, output_name, rename_exc)
                            write_errors.append(f"{output_name}: {exc}")
                    else:
                        write_errors.append(f"{output_name}: {exc}")
                completed_uploads += 1

        await asyncio.gather(*[do_upload(work) for work in work_items])

        if progress_callback:
            progress_callback(98, f"远程 subtitles 回写完成，写入 {len(written_files)}，跳过 {len(skipped_files)}")

        return subtitle_dir, written_files, skipped_files, write_errors

    async def process_remote_folder(
        self,
        library_id: str,
        folder_path: str,
        overwrite: Optional[bool] = None,
        enable_metadata_match: Optional[bool] = None,
        naming_strategy: Optional[str] = None,
        use_filter_rules: Optional[bool] = None,
        subtitle_filter_rules: Optional[List[Dict]] = None,
        ai_match_mode: Optional[str] = None,
        ai_confidence_threshold: Optional[int] = None,
        task_id: str = "",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        file_progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict:
        from ..config.settings import get_config
        from .library_manager import get_library_manager

        config = get_config()
        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        overwrite = getattr(config.rj_subtitle, 'overwrite_existing', False) if overwrite is None else overwrite
        enable_metadata_match = getattr(config.rj_subtitle, 'enable_metadata_match', True) if enable_metadata_match is None else enable_metadata_match
        naming_strategy = self._resolve_naming_strategy(getattr(config.rj_subtitle, 'naming_strategy', 'audio') if naming_strategy is None else naming_strategy)
        use_filter_rules = getattr(config.rj_subtitle, 'use_filter_rules', False) if use_filter_rules is None else use_filter_rules

        if library.type != 'synology_filestation':
            raise ValueError('指定库存不是远程库存')
        if not library.synology:
            raise ValueError('远程库存缺少群晖连接配置')
        if not library.writable:
            raise PermissionError('当前远程库存为只读，无法写入 subtitles 目录')

        if should_cancel and should_cancel():
            raise asyncio.CancelledError()

        folder_name = PurePosixPath(folder_path).name or folder_path
        rjcode = self.extract_rjcode(folder_name) or self.extract_rjcode(folder_path)
        if not rjcode:
            raise ValueError("无法从文件夹路径中识别 RJ 号")

        if progress_callback:
            progress_callback(8, '读取远程音频清单')

        # 使用全局缓存 client，避免重复登录
        cached_client = manager.get_cached_synology_client(library.synology)
        folder_info = await manager.folder_contents(library_id, folder_path, client=cached_client, prefer_index=False)
        remote_items = folder_info.get('items') or []
        audio_entries = self._collect_remote_audio_entries(remote_items)
        if not audio_entries:
            raise ValueError('RJ 文件夹中没有找到音频文件')

        if progress_callback:
            progress_callback(10, f"已识别 {len(audio_entries)} 个远程音频")

        if should_cancel and should_cancel():
            raise asyncio.CancelledError()

        source, attempts = await self.find_best_subtitle_source(
            rjcode,
            progress_callback=progress_callback,
        )
        if not source:
            return {
                'success': False,
                'rjcode': rjcode,
                'error': '未找到可用的中文字幕来源',
                'search_attempts': attempts,
            }

        if progress_callback:
            progress_callback(28, f"发现字幕来源 {source['rjcode']}")

        temp_root = os.path.join(config.storage.temp_path, 'rj_subtitle_fetch')
        os.makedirs(temp_root, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix=f"{rjcode}_", dir=temp_root)

        downloaded_files = []
        content_deduped_files: List[Dict] = []
        failed_files = []
        subtitle_candidates_source = source['subtitle_files']
        initial_candidate_count = len(subtitle_candidates_source)
        if use_filter_rules:
            subtitle_candidates_source = self._apply_subtitle_filter_rules(
                subtitle_candidates_source,
                subtitle_filter_rules or [],
            )
        subtitle_candidates = self._dedupe_subtitle_candidates_for_download(subtitle_candidates_source, audio_entries)
        logger.info(
            '[RJ字幕] 下载前候选统计: 初始=%s 过滤后=%s 下载去重后=%s use_filter_rules=%s',
            initial_candidate_count,
            len(subtitle_candidates_source),
            len(subtitle_candidates),
            bool(use_filter_rules),
        )

        try:
            total_files = len(subtitle_candidates)
            for index, subtitle in enumerate(subtitle_candidates, start=1):
                if should_cancel and should_cancel():
                    raise asyncio.CancelledError()
                subtitle = self._normalize_subtitle_file(subtitle)
                preview_name = self._preview_raw_subtitle_output_name(subtitle)
                rel_path = self._sanitize_relative_path(subtitle.get('relative_path') or subtitle['name'])
                dest_path = os.path.join(temp_dir, rel_path)

                def download_progress(downloaded_bytes: int, total_bytes: int, file_name=preview_name, current=index):
                    if should_cancel and should_cancel():
                        raise asyncio.CancelledError()
                    if file_progress_callback:
                        file_progress_callback(file_name, current, total_files, downloaded_bytes, total_bytes)

                ok = await self.asmr_service.download_file(
                    subtitle['media_download_url'],
                    dest_path,
                    progress_callback=download_progress,
                )

                if ok:
                    downloaded_files.append({
                        'name': preview_name,
                        'source_name': subtitle['name'],
                        'path': dest_path,
                        'relative_path': rel_path,
                        'display_name': preview_name,
                    })
                else:
                    failed_files.append({
                        'name': preview_name,
                        'source_name': subtitle['name'],
                        'reason': '下载失败',
                    })

                if progress_callback:
                    progress = 30 + int((index / max(total_files, 1)) * 35)
                    progress_callback(progress, f"下载字幕 {index}/{total_files}: {preview_name}")

            if not downloaded_files:
                return {
                    'success': False,
                    'rjcode': rjcode,
                    'actual_rjcode': source['rjcode'],
                    'source_lang': source['lang'],
                    'source_title': source['title'],
                    'error': '字幕下载失败或已被过滤规则全部排除',
                    'search_attempts': attempts,
                    'failed_files': failed_files,
                }

            if should_cancel and should_cancel():
                raise asyncio.CancelledError()

            if progress_callback:
                progress_callback(68, '整理字幕内容并准备匹配')

            downloaded_files, content_deduped_files = self._dedupe_downloaded_subtitles_by_content(
                downloaded_files,
                audio_entries,
            )
            if content_deduped_files:
                logger.info('[RJ字幕] 按内容去重后保留 %s 个字幕，合并 %s 个完全重复项', len(downloaded_files), len(content_deduped_files))
            self._prune_temp_subtitle_files(temp_dir, downloaded_files)

            lrc_clean_result = None
            if getattr(config.asmr_sync, 'lrc_clean_enabled', False):
                custom_patterns = getattr(config.asmr_sync, 'lrc_clean_patterns', None)
                lrc_clean_result = self.subtitle_service.clean_lrc_files_in_folder(temp_dir, custom_patterns)

            simplify_result = None
            if getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                simplify_result = self.subtitle_service.convert_subtitles_to_simplified_in_folder(temp_dir)

            if progress_callback:
                progress_callback(80, '匹配远程音频与字幕')

            downloaded_subtitles = self.subtitle_service._scan_subtitle_files(temp_dir)
            if not downloaded_subtitles:
                return {
                    'success': False,
                    'rjcode': rjcode,
                    'actual_rjcode': source['rjcode'],
                    'source_lang': source['lang'],
                    'source_title': source['title'],
                    'error': '下载结果中没有可用字幕文件',
                    'search_attempts': attempts,
                }

            if progress_callback:
                match_step = '匹配远程音频与字幕（远程目录暂不读取 metadata）' if enable_metadata_match else '匹配远程音频与字幕'
                progress_callback(84, match_step)

            if should_cancel and should_cancel():
                raise asyncio.CancelledError()

            match_result = self.match_subtitles_to_audio(
                audio_entries,
                downloaded_subtitles,
                enable_metadata_match=False,
                naming_strategy=naming_strategy,
            )

            ai_result = await self._maybe_apply_ai_auto_match(
                audio_files=audio_entries,
                subtitle_files=downloaded_subtitles,
                base_match_result=match_result,
                enable_metadata_match=False,
                naming_strategy=naming_strategy,
                ai_match_mode=ai_match_mode,
                ai_confidence_threshold=ai_confidence_threshold,
                task_id=task_id,
                rjcode=rjcode,
                progress_callback=progress_callback,
            )
            match_result = ai_result.get('match_result') or match_result
            ai_metadata = ai_result.get('metadata') or {}
            ai_auto_applied = bool(ai_metadata.get('ai_auto_applied'))
            if ai_auto_applied:
                subtitle_dir_preview = await self._ensure_remote_subtitle_dir(cached_client, folder_path)
                existing_names = await self._get_remote_existing_subtitle_names(cached_client, subtitle_dir_preview)
                conflicts = self._validate_ai_auto_output_conflicts(match_result, existing_names, overwrite)
                if conflicts:
                    ai_metadata = self._downgrade_ai_auto_to_manual(
                        ai_metadata,
                        match_result,
                        f"overwrite_conflict:{', '.join(conflicts[:5])}",
                    )
                    ai_auto_applied = False
            awaiting_manual_match = bool(ai_result.get('used')) and not ai_auto_applied
            if ai_auto_applied:
                self._annotate_download_display_names(downloaded_files, match_result)

            if progress_callback:
                progress_callback(92, '回写远程 subtitles 目录')

            if should_cancel and should_cancel():
                raise asyncio.CancelledError()

            if ai_auto_applied:
                subtitle_dir, written_files, skipped_files, write_errors = await self._write_remote_subtitles(
                    library_id=library_id,
                    folder_path=folder_path,
                    match_result=match_result,
                    overwrite=overwrite,
                    temp_dir=temp_dir,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
            else:
                subtitle_dir, written_files, skipped_files, write_errors = await self._write_remote_downloaded_subtitles(
                    library_id=library_id,
                    folder_path=folder_path,
                    downloaded_files=downloaded_files,
                    overwrite=overwrite,
                    temp_dir=temp_dir,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )

            has_output = len(written_files) > 0 or len(skipped_files) > 0
            success = has_output
            partial = has_output and (
                len(skipped_files) > 0 or
                len(write_errors) > 0 or
                len(failed_files) > 0 or
                len(match_result['unmatched_audio']) > 0 or
                len(match_result['unmatched_subtitles']) > 0
            )

            return {
                'success': success,
                'partial': partial,
                'rjcode': rjcode,
                'actual_rjcode': source['rjcode'],
                'source_lang': source['lang'],
                'source_work_type': source['work_type'],
                'source_title': source['title'],
                'search_attempts': attempts,
                'downloaded_count': len(downloaded_files),
                'download_files': downloaded_files,
                'failed_files': failed_files,
                'lrc_clean_result': lrc_clean_result,
                'simplify_result': simplify_result,
                'match_result': match_result,
                'written_files': written_files,
                'skipped_files': skipped_files,
                'write_errors': write_errors,
                'subtitle_dir': subtitle_dir,
                'existing_subtitle_count': self._count_remote_existing_subtitles(remote_items),
                'awaiting_manual_match': awaiting_manual_match,
                **ai_metadata,
                'error': None if success else '未能匹配并写入任何字幕文件',
            }
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    async def process_folder(
        self,
        folder_path: str,
        library_id: Optional[str] = None,
        overwrite: Optional[bool] = None,
        enable_metadata_match: Optional[bool] = None,
        naming_strategy: Optional[str] = None,
        use_filter_rules: Optional[bool] = None,
        subtitle_filter_rules: Optional[List[Dict]] = None,
        ai_match_mode: Optional[str] = None,
        ai_confidence_threshold: Optional[int] = None,
        task_id: str = "",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        file_progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict:
        """处理单个 RJ 文件夹"""
        from ..config.settings import get_config

        if library_id:
            return await self.process_remote_folder(
                library_id=library_id,
                folder_path=folder_path,
                overwrite=overwrite,
                enable_metadata_match=enable_metadata_match,
                naming_strategy=naming_strategy,
                use_filter_rules=use_filter_rules,
                subtitle_filter_rules=subtitle_filter_rules,
                ai_match_mode=ai_match_mode,
                ai_confidence_threshold=ai_confidence_threshold,
                task_id=task_id,
                progress_callback=progress_callback,
                file_progress_callback=file_progress_callback,
                should_cancel=should_cancel,
            )

        config = get_config()
        folder = Path(folder_path)
        overwrite = getattr(config.rj_subtitle, 'overwrite_existing', False) if overwrite is None else overwrite
        enable_metadata_match = getattr(config.rj_subtitle, 'enable_metadata_match', True) if enable_metadata_match is None else enable_metadata_match
        naming_strategy = self._resolve_naming_strategy(getattr(config.rj_subtitle, 'naming_strategy', 'audio') if naming_strategy is None else naming_strategy)
        use_filter_rules = getattr(config.rj_subtitle, 'use_filter_rules', False) if use_filter_rules is None else use_filter_rules
        rjcode = self.extract_rjcode(folder.name) or self.extract_rjcode(str(folder))

        if not rjcode:
            raise ValueError("无法从文件夹路径中识别 RJ 号")

        if should_cancel and should_cancel():
            raise asyncio.CancelledError()

        audio_files = self._collect_audio_files(folder)
        if not audio_files:
            raise ValueError("RJ 文件夹中没有找到音频文件")

        if progress_callback:
            progress_callback(8, "扫描本地音频文件")

        if progress_callback:
            progress_callback(10, f"已识别 {len(audio_files)} 个本地音频")

        if should_cancel and should_cancel():
            raise asyncio.CancelledError()

        source, attempts = await self.find_best_subtitle_source(
            rjcode,
            progress_callback=progress_callback,
        )
        if not source:
            return {
                'success': False,
                'rjcode': rjcode,
                'error': '未找到可用的中文字幕来源',
                'search_attempts': attempts,
            }

        if progress_callback:
            progress_callback(28, f"发现字幕来源 {source['rjcode']}")

        temp_root = os.path.join(config.storage.temp_path, 'rj_subtitle_fetch')
        os.makedirs(temp_root, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix=f"{rjcode}_", dir=temp_root)

        downloaded_files = []
        content_deduped_files: List[Dict] = []
        failed_files = []
        subtitle_candidates_source = source['subtitle_files']
        initial_candidate_count = len(subtitle_candidates_source)
        if use_filter_rules:
            subtitle_candidates_source = self._apply_subtitle_filter_rules(
                subtitle_candidates_source,
                subtitle_filter_rules or [],
            )
        subtitle_candidates = self._dedupe_subtitle_candidates_for_download(subtitle_candidates_source, audio_files)
        logger.info(
            '[RJ字幕] 下载前候选统计: 初始=%s 过滤后=%s 下载去重后=%s use_filter_rules=%s',
            initial_candidate_count,
            len(subtitle_candidates_source),
            len(subtitle_candidates),
            bool(use_filter_rules),
        )

        try:
            total_files = len(subtitle_candidates)
            for index, subtitle in enumerate(subtitle_candidates, start=1):
                if should_cancel and should_cancel():
                    raise asyncio.CancelledError()
                subtitle = self._normalize_subtitle_file(subtitle)
                preview_name = self._preview_raw_subtitle_output_name(subtitle)
                rel_path = self._sanitize_relative_path(subtitle.get('relative_path') or subtitle['name'])
                dest_path = os.path.join(temp_dir, rel_path)

                def download_progress(downloaded_bytes: int, total_bytes: int, file_name=preview_name, current=index):
                    if should_cancel and should_cancel():
                        raise asyncio.CancelledError()
                    if file_progress_callback:
                        file_progress_callback(file_name, current, total_files, downloaded_bytes, total_bytes)

                ok = await self.asmr_service.download_file(
                    subtitle['media_download_url'],
                    dest_path,
                    progress_callback=download_progress,
                )

                if ok:
                    downloaded_files.append({
                        'name': preview_name,
                        'source_name': subtitle['name'],
                        'path': dest_path,
                        'relative_path': rel_path,
                        'display_name': preview_name,
                    })
                else:
                    failed_files.append({
                        'name': preview_name,
                        'source_name': subtitle['name'],
                        'reason': '下载失败',
                    })

                if progress_callback:
                    progress = 30 + int((index / max(total_files, 1)) * 35)
                    progress_callback(progress, f"下载字幕 {index}/{total_files}: {preview_name}")

            if not downloaded_files:
                return {
                    'success': False,
                    'rjcode': rjcode,
                    'actual_rjcode': source['rjcode'],
                    'source_lang': source['lang'],
                    'source_title': source['title'],
                    'error': '字幕下载失败或已被过滤规则全部排除',
                    'search_attempts': attempts,
                    'failed_files': failed_files,
                }

            if should_cancel and should_cancel():
                raise asyncio.CancelledError()

            if progress_callback:
                progress_callback(68, '整理字幕内容并准备匹配')

            downloaded_files, content_deduped_files = self._dedupe_downloaded_subtitles_by_content(
                downloaded_files,
                audio_files,
            )
            if content_deduped_files:
                logger.info('[RJ字幕] 按内容去重后保留 %s 个字幕，合并 %s 个完全重复项', len(downloaded_files), len(content_deduped_files))
            self._prune_temp_subtitle_files(temp_dir, downloaded_files)

            lrc_clean_result = None
            if getattr(config.asmr_sync, 'lrc_clean_enabled', False):
                custom_patterns = getattr(config.asmr_sync, 'lrc_clean_patterns', None)
                lrc_clean_result = self.subtitle_service.clean_lrc_files_in_folder(temp_dir, custom_patterns)

            simplify_result = None
            if getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                simplify_result = self.subtitle_service.convert_subtitles_to_simplified_in_folder(temp_dir)

            if progress_callback:
                progress_callback(80, "匹配音频与字幕")

            downloaded_subtitles = self.subtitle_service._scan_subtitle_files(temp_dir)
            if not downloaded_subtitles:
                return {
                    'success': False,
                    'rjcode': rjcode,
                    'actual_rjcode': source['rjcode'],
                    'source_lang': source['lang'],
                    'source_title': source['title'],
                    'error': '下载结果中没有可用字幕文件',
                    'search_attempts': attempts,
                }

            if progress_callback:
                match_step = "匹配本地音频与字幕（含 metadata）" if enable_metadata_match else "匹配本地音频与字幕"
                progress_callback(84, match_step)

            if should_cancel and should_cancel():
                raise asyncio.CancelledError()

            match_result = self.match_subtitles_to_audio(
                audio_files,
                downloaded_subtitles,
                enable_metadata_match=enable_metadata_match,
                naming_strategy=naming_strategy,
            )
            ai_result = await self._maybe_apply_ai_auto_match(
                audio_files=audio_files,
                subtitle_files=downloaded_subtitles,
                base_match_result=match_result,
                enable_metadata_match=enable_metadata_match,
                naming_strategy=naming_strategy,
                ai_match_mode=ai_match_mode,
                ai_confidence_threshold=ai_confidence_threshold,
                task_id=task_id,
                rjcode=rjcode,
                progress_callback=progress_callback,
            )
            match_result = ai_result.get('match_result') or match_result
            ai_metadata = ai_result.get('metadata') or {}
            ai_auto_applied = bool(ai_metadata.get('ai_auto_applied'))
            if ai_auto_applied:
                subtitle_dir_preview = folder / 'subtitles'
                existing_names = self._list_local_existing_subtitle_names(subtitle_dir_preview)
                conflicts = self._validate_ai_auto_output_conflicts(match_result, existing_names, overwrite)
                if conflicts:
                    ai_metadata = self._downgrade_ai_auto_to_manual(
                        ai_metadata,
                        match_result,
                        f"overwrite_conflict:{', '.join(conflicts[:5])}",
                    )
                    ai_auto_applied = False
            awaiting_manual_match = bool(ai_result.get('used')) and not ai_auto_applied
            if ai_auto_applied:
                self._annotate_download_display_names(downloaded_files, match_result)

            if ai_auto_applied:
                subtitle_dir, written_files, skipped_files, write_errors = self._write_local_matched_subtitles(
                    folder=folder,
                    match_result=match_result,
                    overwrite=overwrite,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
            else:
                subtitle_dir, written_files, skipped_files, write_errors = self._write_local_downloaded_subtitles(
                    folder=folder,
                    downloaded_files=downloaded_files,
                    overwrite=overwrite,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )

            if progress_callback:
                progress_callback(96, "写入 subtitles 目录")

            has_output = len(written_files) > 0 or len(skipped_files) > 0
            success = has_output
            partial = has_output and (
                len(skipped_files) > 0 or
                len(write_errors) > 0 or
                len(failed_files) > 0 or
                len(match_result['unmatched_audio']) > 0 or
                len(match_result['unmatched_subtitles']) > 0
            )

            return {
                'success': success,
                'partial': partial,
                'rjcode': rjcode,
                'actual_rjcode': source['rjcode'],
                'source_lang': source['lang'],
                'source_work_type': source['work_type'],
                'source_title': source['title'],
                'search_attempts': attempts,
                'downloaded_count': len(downloaded_files),
                'download_files': downloaded_files,
                'failed_files': failed_files,
                'lrc_clean_result': lrc_clean_result,
                'simplify_result': simplify_result,
                'match_result': match_result,
                'written_files': written_files,
                'skipped_files': skipped_files,
                'write_errors': write_errors,
                'subtitle_dir': subtitle_dir,
                'awaiting_manual_match': awaiting_manual_match,
                **ai_metadata,
                'error': None if success else '未能匹配并写入任何字幕文件',
            }
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)


_rj_subtitle_service: Optional[RJSubtitleService] = None


def get_rj_subtitle_service() -> RJSubtitleService:
    global _rj_subtitle_service
    if _rj_subtitle_service is None:
        _rj_subtitle_service = RJSubtitleService()
    return _rj_subtitle_service
