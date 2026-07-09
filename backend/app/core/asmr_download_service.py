"""
ASMR.one 下载服务
从 asmr.one API 获取作品信息并下载文件
支持按语言优先级搜索关联版本（简中 > 繁中 > 日文）
"""
import os
import re
import aiohttp
import asyncio
import logging
import time
from typing import Any, Optional, List, Dict, Callable, Tuple
from pathlib import Path
from datetime import datetime
from yarl import URL

from ..config.settings import get_config
from .log_sanitizer import mask_url_for_log, sanitize_for_log, sanitize_text_for_log
from .resource_budget_service import get_resource_budget_service
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)

ASMR_DOWNLOAD_STREAM_CHUNK_BYTES = 256 * 1024

# 语言优先级定义（数字越小优先级越高）
LANGUAGE_PRIORITY = {
    'CHI_HANS': 1,  # 简体中文
    'CHI_SIMP': 1,  # 简体中文（别名）
    'CHI_HANT': 2,  # 繁体中文
    'CHI_TRAD': 2,  # 繁体中文（别名）
    'JPN': 3,       # 日文（原版）
    'JAP': 3,       # 日文（别名）
    'ENG': 4,       # 英文
    'KOR': 5,       # 韩文
}


class LinkedWorkInfo:
    """关联作品信息"""
    def __init__(self, workno: str, lang: str = 'JPN', work_type: str = 'original'):
        self.workno = workno
        self.lang = lang
        self.work_type = work_type  # original, parent, child

    @property
    def priority(self) -> int:
        """获取语言优先级"""
        return LANGUAGE_PRIORITY.get(self.lang, 99)


class ASMRDownloadService:
    """ASMR.one 下载服务"""

    # API 基础 URL 列表（用于故障转移）
    API_BASE_URLS = [
        "https://api.asmr-200.com/api",
        "https://api.asmr-100.com/api",
    ]
    CIRCUIT_FAILURE_THRESHOLD = 6
    CIRCUIT_OPEN_SECONDS = 300

    # DLsite API
    DLSITE_API = "https://www.dlsite.com/maniax/api/=/product.json"

    def __init__(self, config=None):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._current_api_index = 0
        self._api_failure_count = 0
        self._api_circuit_open_until = 0.0
        self._api_circuit_reason = ""
        # linked_* 关联作品信息缓存：key=f"linked_{workno}"；TTL+LRU 控上限
        self._cache: TTLCache = TTLCache(max_size=1024, ttl_seconds=300, name="asmr_download.linked")
        self._cache_ttl = 300  # 5分钟缓存（给现有内层 TTL 判定用，兼容）

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_api_base(self) -> str:
        """获取当前 API 基础 URL"""
        return self.API_BASE_URLS[self._current_api_index]

    async def _switch_api(self):
        """切换到下一个 API 服务器"""
        self._current_api_index = (self._current_api_index + 1) % len(self.API_BASE_URLS)
        logger.info(f"切换 API 服务器到: {self._get_api_base()}")

    def _asmr_api_circuit_remaining(self) -> int:
        remaining = int(max(0.0, self._api_circuit_open_until - time.monotonic()))
        return remaining

    def _asmr_api_circuit_open(self) -> bool:
        return self._asmr_api_circuit_remaining() > 0

    def _record_asmr_api_success(self) -> None:
        self._api_failure_count = 0
        self._api_circuit_open_until = 0.0
        self._api_circuit_reason = ""

    def _record_asmr_api_failure(self, reason: str) -> None:
        self._api_failure_count += 1
        self._api_circuit_reason = str(reason or "request_failed")[:200]
        if self._api_failure_count < self.CIRCUIT_FAILURE_THRESHOLD:
            return
        self._api_circuit_open_until = time.monotonic() + self.CIRCUIT_OPEN_SECONDS
        logger.warning(
            "[ASMR] API 连续失败 %s 次，熔断 %s 秒，期间跳过 asmr.one 请求: %s",
            self._api_failure_count,
            self.CIRCUIT_OPEN_SECONDS,
            self._api_circuit_reason,
        )

    def _skip_asmr_api_when_circuit_open(self, action: str, rjcode: str) -> bool:
        remaining = self._asmr_api_circuit_remaining()
        if remaining <= 0:
            return False
        logger.warning(
            "[ASMR] API 熔断中，跳过%s rj=%s remaining=%ss reason=%s",
            action,
            rjcode,
            remaining,
            self._api_circuit_reason or "连续失败",
        )
        return True

    def _get_runtime_config(self):
        """Return the latest ASMR sync config so proxy changes apply immediately."""
        if self.config is not None:
            return getattr(self.config, "asmr_sync", self.config)
        try:
            return get_config().asmr_sync
        except Exception:
            return None

    def _get_proxy(self) -> Optional[str]:
        config = self._get_runtime_config()
        proxy = getattr(config, "http_proxy", None) if config else None
        if not proxy:
            return None

        proxy = str(proxy).strip()
        if not proxy:
            return None

        if "://" not in proxy:
            proxy = f"http://{proxy}"
        return proxy

    def _mask_proxy(self, proxy: Optional[str]) -> str:
        if not proxy:
            return ""
        return re.sub(r"//([^/@]+)@", "//***:***@", proxy)

    def _proxy_request_kwargs(self) -> Dict:
        proxy = self._get_proxy()
        return {"proxy": proxy} if proxy else {}

    def _browser_like_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/134.0.0.0 Safari/537.36"
            ),
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _download_headers(self) -> Dict[str, str]:
        headers = self._browser_like_headers()
        headers["Accept"] = "*/*"
        return headers

    def _build_download_request_url(self, url: str):
        raw_url = str(url or "").strip()
        if not raw_url:
            return raw_url
        try:
            # 保留源站返回的原始百分号编码，避免 yarl/aiohttp 二次规范化后把路径字节改坏。
            return URL(raw_url, encoded=True)
        except Exception:
            return raw_url

    async def _legacy_test_connectivity(self) -> Dict:
        """测试 ASMR API 与 DLsite 的基本连通性。"""
        session = await self._get_session()
        request_kwargs = self._proxy_request_kwargs()
        request_kwargs = self._proxy_request_kwargs()
        request_kwargs = self._proxy_request_kwargs()
        checks = []

        async def run_check(name: str, url: str):
            started_at = time.perf_counter()
            try:
                timeout = aiohttp.ClientTimeout(total=15, connect=5)
                async with session.get(url, timeout=timeout) as response:
                    latency_ms = int((time.perf_counter() - started_at) * 1000)
                    reachable = response.status < 500
                    checks.append({
                        'name': name,
                        'url': url,
                        'ok': reachable,
                        'status': 'ok' if reachable else 'error',
                        'http_status': response.status,
                        'latency_ms': latency_ms,
                        'message': '可连接' if reachable else f'HTTP {response.status}',
                    })
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                checks.append({
                    'name': name,
                    'url': url,
                    'ok': False,
                    'status': 'timeout',
                    'http_status': None,
                    'latency_ms': latency_ms,
                    'message': '连接超时',
                })
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                checks.append({
                    'name': name,
                    'url': url,
                    'ok': False,
                    'status': 'error',
                    'http_status': None,
                    'latency_ms': latency_ms,
                    'message': str(exc),
                })

        await run_check('ASMR.one 主节点', f'{self.API_BASE_URLS[0]}/workInfo/00000000')
        if len(self.API_BASE_URLS) > 1:
            await run_check('ASMR.one 备用节点', f'{self.API_BASE_URLS[1]}/workInfo/00000000')
        await run_check('DLsite 关联接口', f'{self.DLSITE_API}?workno=RJ00000000')

        ok_count = len([item for item in checks if item['ok']])
        return {
            'success': ok_count > 0,
            'summary': {
                'total': len(checks),
                'ok': ok_count,
                'failed': len(checks) - ok_count,
            },
            'checks': checks,
            'current_api_base': self._get_api_base(),
            'tested_at': datetime.now().isoformat(),
        }

    async def test_connectivity(self) -> Dict:
        """Test ASMR.one primary and fallback API connectivity."""
        session = await self._get_session()
        checks = []
        proxy = self._get_proxy()
        request_kwargs = self._proxy_request_kwargs()

        async def run_check(name: str, url: str):
            started_at = time.perf_counter()
            try:
                timeout = aiohttp.ClientTimeout(total=15, connect=5)
                async with session.get(url, timeout=timeout, **request_kwargs) as response:
                    latency_ms = int((time.perf_counter() - started_at) * 1000)
                    reachable = response.status < 500
                    checks.append({
                        'name': name,
                        'url': url,
                        'ok': reachable,
                        'status': 'ok' if reachable else 'error',
                        'http_status': response.status,
                        'latency_ms': latency_ms,
                        'message': (
                            '节点可达（404 代表接口在线）'
                            if reachable and response.status == 404
                            else ('可连接' if reachable else f'HTTP {response.status}')
                        ),
                    })
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                checks.append({
                    'name': name,
                    'url': url,
                    'ok': False,
                    'status': 'timeout',
                    'http_status': None,
                    'latency_ms': latency_ms,
                    'message': '连接超时',
                })
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                checks.append({
                    'name': name,
                    'url': url,
                    'ok': False,
                    'status': 'error',
                    'http_status': None,
                    'latency_ms': latency_ms,
                    'message': str(exc),
                })

        await run_check('ASMR.one 主节点', f'{self.API_BASE_URLS[0]}/workInfo/00000000')
        if len(self.API_BASE_URLS) > 1:
            await run_check('ASMR.one 备用节点', f'{self.API_BASE_URLS[1]}/workInfo/00000000')

        ok_count = len([item for item in checks if item['ok']])
        return {
            'success': ok_count > 0,
            'summary': {
                'total': len(checks),
                'ok': ok_count,
                'failed': len(checks) - ok_count,
            },
            'checks': checks,
            'current_api_base': self._get_api_base(),
            'proxy_enabled': bool(proxy),
            'proxy_url': self._mask_proxy(proxy),
            'tested_at': datetime.now().isoformat(),
        }

    async def get_linked_works_from_dlsite(self, rjcode: str) -> List[LinkedWorkInfo]:
        """
        从 DLsite API 获取作品的所有关联版本

        Args:
            rjcode: RJ号

        Returns:
            关联作品列表（已按语言优先级排序）
        """
        # 标准化 RJ 号
        if rjcode.upper().startswith('RJ'):
            rjcode_num = rjcode[2:]
        else:
            rjcode_num = rjcode

        # 检查缓存
        cache_key = f"linked_{rjcode_num}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if (datetime.now() - cached['timestamp']).total_seconds() < self._cache_ttl:
                return cached['data']

        works: List[LinkedWorkInfo] = []
        try:
            from .dlsite_service import get_dlsite_service

            linked_map = await get_dlsite_service().get_linked_works(f"RJ{rjcode_num}")
            type_map = {
                'original': 'original',
                'translation': 'translation',
                'parent': 'parent',
                'child': 'child',
                'child_translation': 'child',
            }
            for workno, linked_work in (linked_map or {}).items():
                normalized_workno = str(workno or '').strip().upper()
                if not normalized_workno:
                    continue
                works.append(LinkedWorkInfo(
                    normalized_workno,
                    str(getattr(linked_work, 'lang', 'JPN') or 'JPN').strip() or 'JPN',
                    type_map.get(str(getattr(linked_work, 'work_type', '') or '').strip().lower(), 'translation'),
                ))
        except Exception as e:
            logger.error(f"[DLsite] 获取关联作品失败: {e}")
            if not works:
                works.append(LinkedWorkInfo(f"RJ{rjcode_num}", 'JPN', 'original'))

        deduped: List[LinkedWorkInfo] = []
        seen_worknos = set()
        for work in works:
            if work.workno in seen_worknos:
                continue
            seen_worknos.add(work.workno)
            deduped.append(work)
        works = deduped

        # 按语言优先级排序
        works.sort(key=lambda w: w.priority)

        # 缓存结果
        self._cache[cache_key] = {
            'data': works,
            'timestamp': datetime.now()
        }

        logger.info(f"[DLsite] 找到 {len(works)} 个关联版本: {[(w.workno, w.lang) for w in works]}")
        return works

    async def fetch_work_info(self, rjcode: str) -> Optional[Dict]:
        """
        从 asmr.one API 获取作品信息

        Args:
            rjcode: RJ号，如 "RJ123456" 或 "123456"

        Returns:
            作品信息字典，包含标题、文件列表等
        """
        if self._skip_asmr_api_when_circuit_open("作品信息请求", rjcode):
            return None
        # 标准化 RJ 号
        if rjcode.upper().startswith('RJ'):
            rjcode_num = rjcode[2:]
        else:
            rjcode_num = rjcode

        session = await self._get_session()
        request_kwargs = self._proxy_request_kwargs()

        # 尝试所有 API 服务器
        for attempt in range(len(self.API_BASE_URLS)):
            api_base = self._get_api_base()
            url = f"{api_base}/workInfo/{rjcode_num}"

            try:
                logger.info(f"[ASMR] 获取作品信息: {url}")
                async with session.get(url, **request_kwargs) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._record_asmr_api_success()
                        logger.info(f"[ASMR] 成功获取作品信息: {data.get('title', '未知标题')}")
                        return data
                    elif response.status == 404:
                        self._record_asmr_api_success()
                        logger.warning(f"[ASMR] 作品不存在: {rjcode}")
                        return None
                    else:
                        self._record_asmr_api_failure(f"workInfo HTTP {response.status}")
                        logger.warning(f"[ASMR] 获取作品信息失败: HTTP {response.status}")
                        if self._asmr_api_circuit_open():
                            return None
                        await self._switch_api()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self._record_asmr_api_failure(e.__class__.__name__)
                logger.error(f"[ASMR] 请求作品信息失败: {e}")
                if self._asmr_api_circuit_open():
                    return None
                await self._switch_api()

        logger.error(f"[ASMR] 所有 API 服务器都无法访问: {rjcode}")
        return None

    async def find_best_available_work(self, rjcode: str) -> Tuple[Optional[str], Optional[Dict]]:
        """
        查找最佳可用版本

        按简中 > 繁中 > 日文优先级搜索，返回第一个在 asmr.one 上可用的版本

        Args:
            rjcode: 原始 RJ号

        Returns:
            (可用RJ号, 作品信息) 或 (None, None)
        """
        # 获取所有关联版本
        linked_works = await self.get_linked_works_from_dlsite(rjcode)

        logger.info(f"[搜索] 开始按优先级搜索可用版本，共 {len(linked_works)} 个候选")

        for work in linked_works:
            logger.info(f"[搜索] 尝试: {work.workno} (语言: {work.lang}, 优先级: {work.priority})")

            work_info = await self.fetch_work_info(work.workno)
            if work_info:
                # 检查是否有文件
                tracks = await self.fetch_track_list(work.workno)
                if tracks:
                    logger.info(f"[搜索] 找到可用版本: {work.workno} ({work.lang})")
                    return work.workno, work_info

            # 添加延迟避免请求过快
            await asyncio.sleep(0.5)

        logger.warning(f"[搜索] 未找到任何可用版本: {rjcode}")
        return None, None

    async def fetch_track_list(self, rjcode: str) -> Optional[List[Dict]]:
        """
        获取作品的音轨/文件列表

        Args:
            rjcode: RJ号

        Returns:
            文件列表
        """
        if self._skip_asmr_api_when_circuit_open("文件列表请求", rjcode):
            return None
        # 标准化 RJ 号
        if rjcode.upper().startswith('RJ'):
            rjcode_num = rjcode[2:]
        else:
            rjcode_num = rjcode

        session = await self._get_session()
        request_kwargs = self._proxy_request_kwargs()

        for attempt in range(len(self.API_BASE_URLS)):
            api_base = self._get_api_base()
            url = f"{api_base}/tracks/{rjcode_num}"

            try:
                logger.debug("[ASMR] 获取文件列表: %s", mask_url_for_log(url))
                async with session.get(url, **request_kwargs) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._record_asmr_api_success()
                        file_count = len(data) if isinstance(data, list) else 0
                        logger.debug("[ASMR] 成功获取文件列表: rj=%s count=%s", rjcode, file_count)

                        # 调试：打印第一个文件/文件夹的完整结构
                        if data and isinstance(data, list) and len(data) > 0:
                            first_item = data[0]
                            logger.debug(f"[ASMR] 第一个项目结构: {list(first_item.keys())}")
                            if first_item.get('type') == 'folder' and first_item.get('children'):
                                logger.debug(f"[ASMR] 第一个文件夹名称: {first_item.get('title')}")
                                children = first_item.get('children', [])
                                if children:
                                    logger.debug(f"[ASMR] 第一个子项目结构: {list(children[0].keys())}")
                                    logger.debug(
                                        "[ASMR] 第一个子项目摘要: title=%s size=%s has_download=%s",
                                        children[0].get("title"),
                                        children[0].get("size"),
                                        bool(children[0].get("mediaDownloadUrl") or children[0].get("media_download_url")),
                                    )
                            else:
                                logger.debug(
                                    "[ASMR] 第一个文件摘要: title=%s size=%s has_download=%s",
                                    first_item.get("title"),
                                    first_item.get("size"),
                                    bool(first_item.get("mediaDownloadUrl") or first_item.get("media_download_url")),
                                )

                        return data
                    elif response.status == 404:
                        self._record_asmr_api_success()
                        logger.warning(f"[ASMR] 文件列表不存在: {rjcode}")
                        return []
                    else:
                        self._record_asmr_api_failure(f"tracks HTTP {response.status}")
                        logger.warning(f"[ASMR] 获取文件列表失败: HTTP {response.status}")
                        if self._asmr_api_circuit_open():
                            return None
                        await self._switch_api()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self._record_asmr_api_failure(e.__class__.__name__)
                logger.error(f"[ASMR] 请求文件列表失败: {e}")
                if self._asmr_api_circuit_open():
                    return None
                await self._switch_api()

        logger.error(f"[ASMR] 所有 API 服务器都无法获取文件列表: {rjcode}")
        return None

    def _resolve_track_display_title(self, track: Dict) -> str:
        """优先读取 asmr.one 可能返回的本地化标题，避免只拿原始日文 title。"""
        direct_keys = (
            'display_title', 'displayTitle', 'localized_title', 'localizedTitle',
            'translated_title', 'translatedTitle', 'title_zh', 'titleZh',
            'title_zh_cn', 'titleZhCn', 'title_zh_tw', 'titleZhTw',
            'name_zh', 'nameZh', 'name_zh_cn', 'nameZhCn',
        )
        for key in direct_keys:
            value = str(track.get(key) or '').strip()
            if value:
                return value

        dict_keys = ('title_i18n', 'titleI18n', 'titles', 'name_i18n', 'nameI18n', 'names', 'i18n', 'translation')
        lang_keys = ('zh-cn', 'zh_hans', 'zh-hans', 'chs', 'chi_hans', 'zh-tw', 'zh_hant', 'zh-hant', 'cht', 'chi_hant', 'zh')
        for key in dict_keys:
            value = track.get(key)
            if not isinstance(value, dict):
                continue
            for lang_key in lang_keys:
                candidate = str(value.get(lang_key) or value.get(lang_key.upper()) or '').strip()
                if candidate:
                    return candidate

        return str(track.get('title') or track.get('name') or '').strip()

    def _flatten_tracks(self, tracks: List[Dict], parent_path: str = "", parent_display_path: str = "") -> List[Dict]:
        """
        扁平化音轨列表，提取所有可下载的文件

        Args:
            tracks: 音轨列表
            parent_path: 父级路径

        Returns:
            扁平化的文件列表
        """
        files = []

        for track in tracks:
            # 构建当前路径
            raw_title = track.get('title', '') or track.get('name', '')
            display_title = self._resolve_track_display_title(track)
            current_path = os.path.join(parent_path, raw_title) if parent_path else raw_title
            display_path = os.path.join(parent_display_path, display_title) if parent_display_path else display_title

            if track.get('type') == 'folder':
                # 如果是文件夹，递归处理子项
                children = track.get('children', [])
                files.extend(self._flatten_tracks(children, current_path, display_path))
            else:
                # 如果是文件，添加到列表
                # 支持多种ID字段名：id, hash, media_id
                file_id = track.get('id') or track.get('hash') or track.get('media_id')

                # 获取下载URL - 支持驼峰和下划线两种命名
                download_url = (track.get('mediaDownloadUrl') or
                               track.get('media_download_url') or
                               track.get('downloadUrl') or
                               track.get('download_url'))

                file_info = {
                    'id': file_id,
                    'title': raw_title,
                    'display_title': display_title,
                    'path': current_path,
                    'display_path': display_path,
                    'type': track.get('type'),
                    'media_download_url': download_url,
                    'size': track.get('size', 0),
                    'hash': track.get('hash'),  # ASMR.one 使用 hash 作为下载标识
                }
                files.append(file_info)

                # 调试：打印第一个文件的结构
                if len(files) == 1:
                    logger.debug(
                        "[ASMR] 解析后第一个文件: title=%s download_url=%s",
                        file_info["title"],
                        mask_url_for_log(download_url[:200] if download_url else "None"),
                    )

        return files

    async def download_file(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        max_retries: int = 10,
        timeout: int = 60,
        cancel_check: Optional[Callable[[], bool]] = None,
        pause_wait: Optional[Callable[[], Any]] = None,
    ) -> bool:
        """
        下载单个文件（支持断点续传和重试）

        Args:
            url: 下载 URL
            dest_path: 目标路径
            progress_callback: 进度回调函数 (downloaded_bytes, total_bytes)
            log_callback: 日志回调函数 (message, level)
            max_retries: 最大重试次数（默认10次）
            timeout: 单次请求超时时间（秒，默认60秒）
            cancel_check: 取消检查回调，返回 True 表示已取消
            pause_wait: 暂停等待回调，调用后会阻塞直到恢复

        Returns:
            是否成功
        """
        session = await self._get_session()
        request_kwargs = self._proxy_request_kwargs()
        request_headers = self._download_headers()
        request_url = self._build_download_request_url(url)
        request_url_text = str(request_url)

        def push_log(message: str, level: str = "info") -> None:
            if log_callback:
                try:
                    log_callback(str(message), str(level or "info"))
                except Exception:
                    logger.debug("[下载] 日志回调失败", exc_info=True)

        for attempt in range(max_retries):
            try:
                # 确保目标目录存在
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                # 检查是否有未完成的下载（断点续传）
                temp_path = dest_path + '.downloading'
                resume_offset = 0

                if os.path.exists(temp_path):
                    resume_offset = os.path.getsize(temp_path)
                    logger.debug(f"[下载] 发现未完成文件，从 {resume_offset} 字节处续传: {os.path.basename(dest_path)}")
                    push_log(f"{os.path.basename(dest_path)} 发现未完成片段，准备从 {resume_offset} 字节续传")
                elif os.path.exists(dest_path):
                    # 文件已存在，检查大小是否完整
                    existing_size = os.path.getsize(dest_path)
                    # 先获取远程文件大小
                    push_log(f"{os.path.basename(dest_path)} 检查已存在文件完整性")
                    async with session.head(
                        request_url,
                        headers=request_headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                        **request_kwargs,
                    ) as head_response:
                        if head_response.status == 200:
                            remote_size = int(head_response.headers.get('content-length', 0))
                            if remote_size > 0 and existing_size >= remote_size:
                                logger.debug(f"[下载] 文件已存在且完整，跳过: {os.path.basename(dest_path)}")
                                push_log(f"{os.path.basename(dest_path)} 已存在且完整，跳过下载", "success")
                                return True
                            elif existing_size > 0:
                                # 文件存在但不完整，重命名并续传
                                await asyncio.to_thread(os.rename, dest_path, temp_path)
                                resume_offset = existing_size
                                logger.debug(f"[下载] 文件不完整({existing_size}/{remote_size})，续传: {os.path.basename(dest_path)}")
                                push_log(f"{os.path.basename(dest_path)} 文件不完整，准备续传 {existing_size}/{remote_size}")

                # 构建请求头（支持断点续传）
                headers = dict(request_headers)
                if resume_offset > 0:
                    headers['Range'] = f'bytes={resume_offset}-'

                push_log(f"{os.path.basename(dest_path)} 开始请求资源，第 {attempt + 1}/{max_retries} 次尝试")
                push_log(f"{os.path.basename(dest_path)} 等待源站响应", "info")

                async with get_resource_budget_service().acquire("network_download", reason="asmr.download_file"), session.get(
                    request_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=timeout),
                    **request_kwargs,
                ) as response:
                    # 处理响应状态
                    if resume_offset > 0 and response.status == 206:
                        content_range = response.headers.get('content-range', '')
                        # 严格校验 Content-Range，防止服务端返回错误分片导致追加污染文件尾部。
                        range_match = re.match(r'^bytes\s+(\d+)-(\d+)/(\d+|\*)$', str(content_range).strip(), re.IGNORECASE)
                        if not range_match:
                            logger.warning(f"[下载] 续传响应缺少有效 Content-Range，回退全量重下: {os.path.basename(dest_path)}, content-range={content_range}")
                            push_log(f"{os.path.basename(dest_path)} 续传响应无效，回退全量重下", "warning")
                            if os.path.exists(temp_path):
                                await asyncio.to_thread(os.remove, temp_path)
                            await asyncio.sleep(1)
                            continue

                        range_start = int(range_match.group(1))
                        total_size = int(range_match.group(3)) if range_match.group(3).isdigit() else 0

                        if range_start != resume_offset:
                            logger.warning(
                                "[下载] 续传偏移不匹配，回退全量重下: file=%s, local_offset=%s, server_start=%s, content-range=%s",
                                os.path.basename(dest_path),
                                resume_offset,
                                range_start,
                                content_range,
                            )
                            push_log(
                                f"{os.path.basename(dest_path)} 续传偏移不匹配(local={resume_offset}, remote={range_start})，回退全量重下",
                                "warning",
                            )
                            if os.path.exists(temp_path):
                                await asyncio.to_thread(os.remove, temp_path)
                            await asyncio.sleep(1)
                            continue

                        if total_size > 0 and resume_offset >= total_size:
                            logger.warning(
                                "[下载] 本地续传片段大小异常，回退全量重下: file=%s, local_offset=%s, total=%s",
                                os.path.basename(dest_path),
                                resume_offset,
                                total_size,
                            )
                            push_log(
                                f"{os.path.basename(dest_path)} 本地续传片段异常(local={resume_offset}, total={total_size})，回退全量重下",
                                "warning",
                            )
                            if os.path.exists(temp_path):
                                await asyncio.to_thread(os.remove, temp_path)
                            await asyncio.sleep(1)
                            continue

                        downloaded = resume_offset
                        logger.debug(f"[下载] 服务器支持断点续传，从 {resume_offset}/{total_size} 继续")
                        push_log(f"{os.path.basename(dest_path)} 源站已响应，支持断点续传 {resume_offset}/{total_size}")
                    elif resume_offset > 0 and response.status == 200:
                        # 服务器不支持断点续传，重新下载
                        resume_offset = 0
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        if os.path.exists(temp_path):
                            await asyncio.to_thread(os.remove, temp_path)
                        logger.debug("[下载] 服务器不支持断点续传，重新下载")
                        push_log(f"{os.path.basename(dest_path)} 源站已响应，但不支持断点续传，准备重新下载")
                    elif response.status != 200:
                        logger.error(
                            "[下载] 下载失败: HTTP %s, URL: %s, dest=%s, attempt=%s/%s",
                            response.status,
                            mask_url_for_log(request_url_text),
                            os.path.basename(dest_path),
                            attempt + 1,
                            max_retries,
                        )
                        if attempt < max_retries - 1:
                            wait_time = min(5 * (attempt + 1), 30)  # 递增等待时间，最多30秒
                            logger.debug(f"[下载] 等待 {wait_time} 秒后重试...")
                            push_log(f"{os.path.basename(dest_path)} 源站返回 HTTP {response.status}，{wait_time} 秒后重试", "warning")
                            await asyncio.sleep(wait_time)
                            continue
                        push_log(f"{os.path.basename(dest_path)} 源站返回 HTTP {response.status}，重试已耗尽", "error")
                        return False
                    else:
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        push_log(f"{os.path.basename(dest_path)} 源站已响应，开始接收数据")

                    # 写入文件
                    write_path = temp_path if resume_offset == 0 or response.status == 206 else dest_path
                    mode = 'ab' if resume_offset > 0 and response.status == 206 else 'wb'

                    last_progress_reported = downloaded
                    last_progress_reported_at = time.monotonic()
                    last_signal_check_at = last_progress_reported_at
                    with open(write_path, mode) as f:
                        async for chunk in response.content.iter_chunked(ASMR_DOWNLOAD_STREAM_CHUNK_BYTES):
                            # ── 暂停 / 取消信号检查 ──
                            now_monotonic = time.monotonic()
                            if now_monotonic - last_signal_check_at >= 0.25:
                                last_signal_check_at = now_monotonic
                                if cancel_check and cancel_check():
                                    push_log(f"{os.path.basename(dest_path)} 下载已被用户取消", "warning")
                                    return False
                                if pause_wait:
                                    await pause_wait()

                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                now_monotonic = time.monotonic()
                                should_report = (
                                    downloaded >= total_size
                                    or (downloaded - last_progress_reported) >= 256 * 1024
                                    or (now_monotonic - last_progress_reported_at) >= 0.5
                                )
                                if should_report:
                                    progress_callback(downloaded, total_size)
                                    last_progress_reported = downloaded
                                    last_progress_reported_at = now_monotonic

                    # 下载完成，重命名临时文件
                    if os.path.exists(temp_path):
                        # 避免下载链路把错误内容静默当作成功。
                        actual_size = os.path.getsize(temp_path)
                        if total_size > 0 and actual_size != total_size:
                            logger.warning(
                                "[下载] 下载后大小校验失败，准备重试: file=%s, actual=%s, total=%s",
                                os.path.basename(dest_path),
                                actual_size,
                                total_size,
                            )
                            push_log(
                                f"{os.path.basename(dest_path)} 下载大小校验失败({actual_size}/{total_size})，准备重试",
                                "warning",
                            )
                            await asyncio.sleep(1)
                            continue

                        if os.path.exists(dest_path):
                            await asyncio.to_thread(os.remove, dest_path)
                        await asyncio.to_thread(os.rename, temp_path, dest_path)

                    logger.debug(f"下载完成: {dest_path} ({downloaded} bytes)")
                    push_log(f"{os.path.basename(dest_path)} 下载完成", "success")
                    return True

            except asyncio.TimeoutError:
                logger.warning(f"[下载] 超时({timeout}秒)，第 {attempt + 1}/{max_retries} 次尝试: {os.path.basename(dest_path)}")
                if attempt < max_retries - 1:
                    wait_time = min(5 * (attempt + 1), 30)
                    logger.debug(f"[下载] 等待 {wait_time} 秒后重试...")
                    push_log(f"{os.path.basename(dest_path)} 等待源站响应超时，第 {attempt + 1}/{max_retries} 次尝试失败，{wait_time} 秒后重试", "warning")
                    await asyncio.sleep(wait_time)
                else:
                    push_log(f"{os.path.basename(dest_path)} 等待源站响应超时，重试已耗尽", "error")
            except aiohttp.ClientError as e:
                logger.warning(f"[下载] 连接错误 {e}，第 {attempt + 1}/{max_retries} 次尝试: {os.path.basename(dest_path)}")
                if attempt < max_retries - 1:
                    wait_time = min(5 * (attempt + 1), 30)
                    logger.debug(f"[下载] 等待 {wait_time} 秒后重试...")
                    push_log(f"{os.path.basename(dest_path)} 连接错误：{e}，第 {attempt + 1}/{max_retries} 次尝试失败，{wait_time} 秒后重试", "warning")
                    await asyncio.sleep(wait_time)
                else:
                    push_log(f"{os.path.basename(dest_path)} 连接错误：{e}，重试已耗尽", "error")
            except Exception as e:
                logger.error(f"下载文件失败: {e}")
                if attempt < max_retries - 1:
                    push_log(f"{os.path.basename(dest_path)} 下载异常：{e}，5 秒后重试", "warning")
                    await asyncio.sleep(5)
                else:
                    push_log(f"{os.path.basename(dest_path)} 下载异常：{e}，重试已耗尽", "error")

        # 返回失败，但保留临时文件以支持后续续传
        logger.error(f"[下载] 文件下载失败，已尝试 {max_retries} 次: {os.path.basename(dest_path)}")
        push_log(f"{os.path.basename(dest_path)} 下载失败，已尝试 {max_retries} 次", "error")
        return False

    def filter_files(self, files: List[Dict], filter_rules: List) -> List[Dict]:
        """
        应用筛选规则过滤文件列表

        Args:
            files: 文件列表
            filter_rules: 筛选规则列表（可以是对象或字典）

        Returns:
            过滤后的文件列表
        """
        if not filter_rules:
            logger.debug("[筛选] 没有筛选规则，保留所有文件")
            return files

        # 音频扩展名集合
        audio_extensions = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac'}

        # 先打印所有筛选规则的状态
        logger.debug(f"[筛选] 共有 {len(filter_rules)} 条筛选规则:")
        for i, rule in enumerate(filter_rules):
            if isinstance(rule, dict):
                name = rule.get('name', f'规则{i+1}')
                enabled = rule.get('enabled', True)
                pattern = rule.get('pattern', '')
                target = rule.get('target', 'file')
            else:
                name = getattr(rule, 'name', f'规则{i+1}')
                enabled = getattr(rule, 'enabled', True)
                pattern = getattr(rule, 'pattern', '')
                target = getattr(rule, 'target', 'file')
            status = "启用" if enabled else "禁用"
            logger.debug(f"[筛选]   - {name}: pattern='{pattern}', target='{target}', 状态={status}")

        filtered_files = []
        excluded_count = 0

        # 调试：打印前几个文件名
        if files:
            logger.debug(f"[筛选] 前5个文件名示例:")
            for i, f in enumerate(files[:5]):
                logger.debug(f"[筛选]   {i+1}. title='{f.get('title', '')}', path='{f.get('path', '')}'")

        for file_info in files:
            file_name = file_info.get('title', '')
            file_path = file_info.get('path', file_name)  # 完整路径，包含文件夹名
            ext = os.path.splitext(file_name)[1].lower()

            # 只处理音频文件
            if ext not in audio_extensions:
                # 非音频文件（如图片、文本等）直接保留
                filtered_files.append(file_info)
                continue

            # 应用筛选规则
            should_exclude = False
            for rule in filter_rules:
                # 支持字典和对象两种访问方式
                if isinstance(rule, dict):
                    enabled = rule.get('enabled', True)
                    target = rule.get('target', 'file')
                    pattern = rule.get('pattern', '')
                    name = rule.get('name', '')
                else:
                    enabled = getattr(rule, 'enabled', True)
                    target = getattr(rule, 'target', 'file')
                    pattern = getattr(rule, 'pattern', '')
                    name = getattr(rule, 'name', '')

                if not enabled:
                    continue

                try:
                    # 根据target决定检查什么内容
                    if target == 'folder':
                        # 文件夹规则：检查完整路径（包含文件夹名）
                        check_content = file_path
                    elif target == 'all':
                        # 全部规则：检查路径和文件名
                        check_content = file_path
                    else:
                        # file规则：只检查文件名
                        check_content = file_name

                    if re.search(pattern, check_content, re.IGNORECASE):
                        should_exclude = True
                        logger.debug(f"[筛选] 文件被规则 [{name}] 过滤: {file_path} (匹配'{pattern}')")
                        excluded_count += 1
                        break
                except re.error as e:
                    logger.error(f"正则表达式错误: {pattern}, {e}")

            if not should_exclude:
                filtered_files.append(file_info)

        logger.info(f"[筛选] 原始文件数: {len(files)}, 筛选后: {len(filtered_files)}, 排除: {excluded_count}")
        return filtered_files

    async def download_work(
        self,
        rjcode: str,
        dest_dir: str,
        filter_rules: List = None,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        file_progress_callback: Optional[Callable[[str, int, int, int, int], None]] = None,
        check_pause: Optional[Callable[[], bool]] = None
    ) -> Dict:
        """
        下载整个作品并应用筛选规则
        自动搜索最佳可用版本（简中 > 繁中 > 日文）

        Args:
            rjcode: RJ号
            dest_dir: 目标目录
            filter_rules: 筛选规则列表
            progress_callback: 进度回调 (rjcode, current, total, step)
            file_progress_callback: 文件进度回调 (file_name, file_index, total_files, downloaded_bytes, total_bytes)
            check_pause: 检查是否需要暂停的回调函数，返回True表示需要暂停

        Returns:
            下载结果
        """
        result = {
            'rjcode': rjcode,
            'actual_rjcode': None,  # 实际下载的RJ号
            'success': False,
            'title': '',
            'lang': '',  # 实际下载版本的语言
            'downloaded_files': [],
            'failed_files': [],  # 失败的文件列表
            'filtered_files': [],
            'error': None,
            'tried_versions': [],  # 尝试过的版本列表
            'paused': False  # 是否被暂停
        }

        try:
            # 查找最佳可用版本
            if progress_callback:
                progress_callback(rjcode, 0, 100, "搜索最佳版本...")

            actual_rjcode, work_info = await self.find_best_available_work(rjcode)

            if not work_info:
                result['error'] = '在 asmr.one 上未找到该作品的任何版本'
                return result

            result['actual_rjcode'] = actual_rjcode
            result['title'] = work_info.get('title', '未知标题')
            logger.info(
                "[ASMR] 下载开始: requested=%s actual=%s title=%s",
                rjcode,
                actual_rjcode,
                result["title"],
            )

            # 获取文件列表
            if progress_callback:
                progress_callback(actual_rjcode, 5, 100, "获取文件列表...")

            tracks = await self.fetch_track_list(actual_rjcode)
            if tracks is None:
                result['error'] = '无法获取文件列表'
                return result

            if not tracks:
                result['error'] = '文件列表为空'
                return result

            # 扁平化文件列表
            all_files = self._flatten_tracks(tracks)
            logger.debug(f"作品 {actual_rjcode} 共有 {len(all_files)} 个文件")

            # 应用筛选规则
            if filter_rules:
                logger.debug(f"[筛选] 收到 {len(filter_rules)} 条筛选规则")
                # 详细打印每条规则
                for i, rule in enumerate(filter_rules):
                    if isinstance(rule, dict):
                        logger.debug("[筛选] 规则%s: %s", i + 1, sanitize_for_log(rule))
                    else:
                        logger.debug(
                            f"[筛选] 规则{i+1}: {getattr(rule, 'name', 'unknown')}, enabled={getattr(rule, 'enabled', True)}, pattern={getattr(rule, 'pattern', '')}"
                        )

                filtered_files = self.filter_files(all_files, filter_rules)
                result['filtered_files'] = [f for f in all_files if f not in filtered_files]
                all_files = filtered_files
                logger.info(
                    "[ASMR] 筛选摘要: rj=%s original=%s kept=%s excluded=%s rules=%s",
                    actual_rjcode,
                    len(result["filtered_files"]) + len(all_files),
                    len(all_files),
                    len(result["filtered_files"]),
                    len(filter_rules),
                )
            else:
                logger.warning("[筛选] 没有收到筛选规则，将下载所有文件！")

            if not all_files:
                result['error'] = '筛选后没有可下载的文件'
                return result

            # 创建下载目录
            os.makedirs(dest_dir, exist_ok=True)

            # 下载文件
            total_files = len(all_files)
            failed_files = []  # 记录失败的文件

            for i, file_info in enumerate(all_files):
                # 检查是否需要暂停
                if check_pause and check_pause():
                    result['paused'] = True
                    result['failed_files'] = failed_files
                    logger.info(f"[ASMR] 下载被暂停，已完成 {i}/{total_files} 个文件")
                    return result

                relative_path = file_info.get('path', file_info['title'])
                if progress_callback:
                    progress_callback(actual_rjcode, i + 1, total_files, f"下载: {relative_path[:30]}")

                # 获取下载 URL - 优先使用 API 返回的完整下载链接
                download_url = file_info.get('media_download_url')

                # 如果没有完整链接，尝试通过 hash 构建
                if not download_url:
                    api_base = self._get_api_base()
                    file_hash = file_info.get('hash')
                    if file_hash:
                        download_url = f"{api_base}/download/{file_hash}"
                        logger.debug("[ASMR] 构建下载链接: %s", mask_url_for_log(download_url))

                if not download_url:
                    logger.warning(f"无法获取下载链接: {file_info['title']}")
                    failed_files.append({
                        'path': relative_path,
                        'title': file_info['title'],
                        'reason': '无法获取下载链接'
                    })
                    continue

                # 构建目标路径 - 使用完整路径（包含文件夹层级）
                file_path = os.path.join(dest_dir, relative_path)

                logger.debug(f"[ASMR] 下载文件 ({i+1}/{total_files}): {relative_path}")

                # 文件进度回调包装
                def make_file_callback(fname, findex, ftotal):
                    def cb(downloaded, total):
                        if file_progress_callback:
                            file_progress_callback(fname, findex, ftotal, downloaded, total)
                    return cb

                # 下载文件
                success = await self.download_file(
                    download_url,
                    file_path,
                    progress_callback=make_file_callback(relative_path, i + 1, total_files) if file_progress_callback else None
                )
                if success:
                    result['downloaded_files'].append({
                        'path': file_path,
                        'title': file_info['title'],
                        'relative_path': relative_path,
                        'size': file_info.get('size', 0)
                    })
                else:
                    failed_files.append({
                        'path': relative_path,
                        'title': file_info['title'],
                        'download_url': download_url,
                        'file_info': file_info,
                        'reason': '下载失败'
                    })

            result['failed_files'] = failed_files

            # 如果有失败文件，记录警告但不标记为完全失败（部分文件可能已下载）
            if failed_files:
                logger.warning(
                    "[ASMR] 下载部分失败: rj=%s success=%s failed=%s",
                    actual_rjcode,
                    len(result["downloaded_files"]),
                    len(failed_files),
                )
                for f in failed_files[:5]:  # 只显示前5个
                    logger.debug(f"[ASMR] 失败文件: {f['title']}: {f['reason']}")

            result['success'] = len(result['downloaded_files']) > 0
            logger.info(f"作品 {actual_rjcode} 下载完成，成功 {len(result['downloaded_files'])} 个，失败 {len(failed_files)} 个")

        except Exception as e:
            logger.error("下载作品失败: %s", sanitize_text_for_log(e))
            result['error'] = str(e)

        return result


# 全局服务实例
_asmr_download_service: Optional[ASMRDownloadService] = None


def get_asmr_download_service() -> ASMRDownloadService:
    """获取 ASMR 下载服务实例"""
    global _asmr_download_service
    if _asmr_download_service is None:
        _asmr_download_service = ASMRDownloadService()
    return _asmr_download_service
