"""
Kikoeru 服务器查重服务
支持通过 API 和 Token 访问本地部署的 Kikoeru 服务器进行查重
"""
import logging
import asyncio
import re
import time
import difflib
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import aiohttp
from datetime import datetime, timedelta
from urllib.parse import quote

from ..config.settings import get_config, save_config
from ..core.dlsite_service import get_dlsite_service
from .log_sanitizer import mask_url_for_log, sanitize_for_log, sanitize_text_for_log
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)


@dataclass
class KikoeruServerConfig:
    """Kikoeru 服务器配置"""
    enabled: bool = False
    server_url: str = ""  # 例如: http://192.168.1.100:8088
    username: str = ""    # 登录用户名
    password: str = ""    # 登录密码
    api_token: str = ""   # API 访问令牌（自动获取）
    token_expires: int = 0  # Token 过期时间戳
    timeout: int = 10     # 请求超时(秒)
    cache_ttl: int = 300  # 缓存时间(秒)
    enable_fuzzy_rj_match: bool = False  # 是否允许危险的 RJ ±1 宽容匹配


@dataclass
class KikoeruCheckResult:
    """Kikoeru 服务器查重结果"""
    is_found: bool = False
    rjcode: str = ""
    work_id: int = 0
    title: str = ""
    circle_name: str = ""
    tags: List[str] = field(default_factory=list)
    total_count: int = 0
    source: str = "kikoeru"
    checked_at: datetime = None
    match_type: str = "exact"
    matched_rjcode: str = ""
    tolerance: int = 0
    lyric_status: str = ""
    has_lyric_hint: bool = False
    subtitle_file_count: int = 0
    subtitle_check_source: str = ""
    total_track_count: int = -1  # -1=未查，0=空壳（无任何文件），>0=有文件
    
    def __post_init__(self):
        if self.checked_at is None:
            self.checked_at = datetime.now()
        if self.tags is None:
            self.tags = []


class KikoeruDuplicateService:
    """
    Kikoeru 服务器查重服务
    
    通过调用 Kikoeru API 检查作品是否已存在于 Kikoeru 库中
    支持 API Token 认证
    """
    
    def __init__(self, config: Optional[KikoeruServerConfig] = None):
        self.config = config or self._load_config()
        # rjcode -> (result, timestamp)；原裸 dict 只在 hit 时清过期项，长期运行会累积。
        # TTLCache + LRU 上限 2048，TTL 从 config 或默认 5min 派生；payload 保留 timestamp 兼容旧判断。
        cache_ttl = max(int(getattr(self.config, "cache_ttl", 300) or 300), 60)
        self._cache: TTLCache = TTLCache(max_size=2048, ttl_seconds=cache_ttl, name="kikoeru.result")
        # circle_id 缓存条目很小，但同样需要有上限。TTL 取 max(cache_ttl, 300)。
        self._circle_id_cache: TTLCache = TTLCache(max_size=1024, ttl_seconds=max(cache_ttl, 300), name="kikoeru.circle_id")
        # ★ 性能优化：search 端点的 raw response 任务级缓存。
        # 之前 ``check_duplicate`` 在 ``_cache`` 命中"未命中"且本次 has_linkage_context
        # 时会跳过 cache 重新打 search，给广义 linkage 匹配一次机会——但
        # ``_build_search_url`` 是按 RJ keyword 拼的，response 不会因为 linkage 上下文不同
        # 而变化，重新 search 一定还是同样的"未命中"raw data。这条路径在大批量任务里
        # 反复打无效 search（33 候选作品 × 多个关联 RJ × 每个 candidate 流程都进一次
        # = 数千次浪费）。改后：把 raw data 也缓存按 RJ key，cache 命中"未命中"+linkage
        # 时复用 raw data 重新 _parse_search_result（CPU 操作，不打 HTTP），就能给
        # 广义匹配一次机会而不需要触网。TTL 跟 _cache 一致。
        self._search_response_cache: TTLCache = TTLCache(max_size=2048, ttl_seconds=cache_ttl, name="kikoeru.search_raw")
        self._duplicate_inflight: Dict[Tuple[str, bool, Tuple[str, ...]], asyncio.Future] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_circle_id_cache(self, keyword: str) -> int:
        cache_key = self._normalize_search_text(keyword)
        if not cache_key:
            return 0
        payload = self._circle_id_cache.get(cache_key)
        if not payload:
            return 0
        circle_id, cached_at = payload
        ttl_seconds = max(int(self.config.cache_ttl or 0), 300)
        if datetime.now() - cached_at > timedelta(seconds=ttl_seconds):
            self._circle_id_cache.pop(cache_key, None)
            return 0
        return int(circle_id or 0)

    def _set_circle_id_cache(self, keyword: str, circle_id: int) -> None:
        cache_key = self._normalize_search_text(keyword)
        if not cache_key:
            return
        try:
            normalized_circle_id = int(circle_id or 0)
        except Exception:
            normalized_circle_id = 0
        if normalized_circle_id <= 0:
            return
        self._circle_id_cache[cache_key] = (normalized_circle_id, datetime.now())
    
    def _load_config(self) -> KikoeruServerConfig:
        """从系统配置加载 Kikoeru 服务器配置"""
        config = get_config()
        if hasattr(config, 'kikoeru_server'):
            kikoeru_config = config.kikoeru_server
            return KikoeruServerConfig(
                enabled=kikoeru_config.enabled,
                server_url=kikoeru_config.server_url.rstrip('/'),
                username=kikoeru_config.username,
                password=kikoeru_config.password,
                api_token=kikoeru_config.api_token,
                token_expires=kikoeru_config.token_expires,
                timeout=kikoeru_config.timeout,
                cache_ttl=kikoeru_config.cache_ttl,
                enable_fuzzy_rj_match=bool(getattr(kikoeru_config, 'enable_fuzzy_rj_match', False)),
            )
        else:
            return KikoeruServerConfig()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP Session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    def _is_token_expired(self) -> bool:
        """检查 Token 是否过期"""
        if not self.config.api_token:
            return True
        if self.config.token_expires <= 0:
            return True
        now = int(time.time())
        return now >= self.config.token_expires - 60
    
    async def _login(self) -> bool:
        """通过账号密码登录获取 Token"""
        if not self.config.username or not self.config.password:
            logger.warning("[Kikoeru] 未配置用户名或密码，无法自动获取 Token")
            return False
        
        try:
            session = await self._get_session()
            login_url = f"{self.config.server_url}/api/auth/me"
            
            logger.info(
                "[Kikoeru] 正在登录: username=%s server=%s",
                self.config.username,
                mask_url_for_log(self.config.server_url),
            )
            logger.debug("[Kikoeru] 登录URL: %s", mask_url_for_log(login_url))
            
            headers = {
                'Accept': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            login_data = {
                "name": self.config.username,
                "password": self.config.password
            }
            
            async with session.post(
                login_url,
                json=login_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as response:
                logger.debug(f"[Kikoeru] 登录响应状态: {response.status}")
                content_type = response.headers.get('Content-Type', '')
                logger.debug(f"[Kikoeru] 响应Content-Type: {content_type}")
                
                if response.status == 200:
                    if 'application/json' in content_type:
                        data = await response.json()
                        logger.debug(f"[Kikoeru] 登录响应keys: {list(data.keys())}")
                        
                        token = data.get('token')
                        
                        if token:
                            self.config.api_token = token
                            self.config.token_expires = int(time.time()) + 86400
                            self._save_token_to_config(token, self.config.token_expires)
                            logger.info(f"[Kikoeru] 登录成功，Token 已保存")
                            return True
                        else:
                            logger.error(f"[Kikoeru] 未找到token，可用字段: {list(data.keys())}")
                            return False
                    else:
                        text = sanitize_text_for_log(await response.text(), max_length=300)
                        logger.error(f"[Kikoeru] 响应非JSON: {text}")
                        return False
                        
                elif response.status == 401:
                    logger.error(f"[Kikoeru] 登录401错误: 用户名或密码错误")
                    return False
                elif response.status == 422:
                    error_text = sanitize_text_for_log(await response.text(), max_length=300)
                    logger.error(f"[Kikoeru] 登录422错误: 参数格式错误 - {error_text}")
                    return False
                else:
                    error_text = sanitize_text_for_log(await response.text(), max_length=300)
                    logger.error(f"[Kikoeru] 登录失败 {response.status}: {error_text}")
                    return False
                    
        except Exception as e:
            logger.error("[Kikoeru] 登录异常: %s", sanitize_text_for_log(e))
            return False
    
    def _save_token_to_config(self, token: str, expires: int):
        """保存 Token 到配置文件"""
        try:
            config_to_save = {
                'kikoeru_server': {
                    'api_token': token,
                    'token_expires': expires
                }
            }
            save_config(config_to_save)
            logger.info("[Kikoeru] Token 已保存到配置文件")
        except Exception as e:
            logger.error("[Kikoeru] 保存 Token 失败: %s", sanitize_text_for_log(e))
    
    async def _ensure_valid_token(self) -> bool:
        """确保有有效的 Token，如果没有或过期则自动获取"""
        if not self._is_token_expired():
            return True
        
        if self.config.username and self.config.password:
            return await self._login()
        
        return bool(self.config.api_token)
    
    def _get_cache(self, rjcode: str) -> Optional[KikoeruCheckResult]:
        """从缓存获取结果"""
        if rjcode not in self._cache:
            return None
        
        result, timestamp = self._cache[rjcode]
        if datetime.now() - timestamp > timedelta(seconds=self.config.cache_ttl):
            # 缓存过期
            del self._cache[rjcode]
            return None
        if getattr(result, "is_found", False) and not str(getattr(result, "subtitle_check_source", "") or "").strip():
            del self._cache[rjcode]
            return None
        
        return result
    
    def _set_cache(self, rjcode: str, result: KikoeruCheckResult):
        """设置缓存"""
        self._cache[rjcode] = (result, datetime.now())

    def _maybe_cache_result(
        self,
        rjcode: str,
        result: KikoeruCheckResult,
        use_cache: bool,
    ) -> None:
        """按 match_type 决定要不要把结果写入主缓存。

        ★ ``linkage_match`` 是依赖调用方传入 ``extra_match_rjcodes`` 才能产生的
        广义命中：被广义命中的那个作品的 RJ 不一定等于查询 RJ。如果直接写进
        以查询 RJ 为 key 的主缓存，无上下文调用方下次再查同一 RJ 会拿到一个
        ``matched_rjcode`` 指向别的作品的"诡异命中"。所以此处显式跳过缓存写入，
        让无上下文调用方走一次干净的严格查询，而广义匹配只在调用方再次给出
        关联链时复算（成本可控，5 分钟 TTL 也足够吃住高频场景）。
        """
        if not use_cache:
            return
        if getattr(result, "match_type", "") == "linkage_match":
            return
        self._set_cache(rjcode, result)

    def _build_search_url(self, rjcode: str) -> str:
        """构建按 RJ 号查重的搜索 URL。

        ★ 关键修复（RJ01407907 类痛点终极修正）：完全不带 ``nsfw`` 参数。
        本工具管的是 ASMR / R18 音声作品，链路里几乎所有 work 都打着 R18 标签；
        历史上写死 ``nsfw=0`` 只过 SFW，会让 Kikoeru 把所有 NSFW 作品从
        ``works`` 里剔掉，导致主作品和它的简中翻译版 / 翻译链全军覆没——前端
        就出现了用户反馈的"整条链路未命中"，但其实简中翻译版明明就在 Kikoeru 上。
        干脆不限 nsfw，让服务端按当前账号自身的偏好放行结果，避免我们前置过滤
        把任何作品打掉。
        ``lyric=`` / ``isAdvance=0`` 仍保留，对齐油猴脚本默认 search 模板，避免
        部分 Kikoeru 部署在缺省语义下走"高级搜索"模式打偏 keyword。
        """
        return (
            f"{self.config.server_url}/api/search"
            f"?page=1"
            f"&sort=desc"
            f"&order=release"
            f"&lyric="
            f"&isAdvance=0"
            f"&keyword={rjcode}"
        )

    def _build_keyword_search_url(self, keyword: str, page: int = 1) -> str:
        encoded = quote(str(keyword or "").strip())
        return (
            f"{self.config.server_url}/api/search"
            f"?page={max(1, int(page))}"
            f"&sort=desc"
            f"&order=created_at"
            f"&nsfw=2"
            f"&lyric="
            f"&keyword={encoded}"
        )

    def _build_keyword_works_page_url(self, keyword: str) -> str:
        encoded = quote(str(keyword or "").strip())
        return f"{self.config.server_url}/works?keyword={encoded}"

    def _build_circle_works_url(self, circle_id: int, page: int = 1) -> str:
        return (
            f"{self.config.server_url}/api/circles/{int(circle_id)}/works"
            f"?page={max(1, int(page))}"
            f"&sort=desc"
            f"&order=created_at"
            f"&nsfw=2"
            f"&lyric="
            f"&seed=7"
            f"&isAdvance=0"
        )

    def _build_tracks_url(self, work_id: int) -> str:
        return f"{self.config.server_url}/api/tracks/{int(work_id)}"

    def _rjcode_to_work_id_str(self, rjcode: str) -> str:
        """RJ 数字部分原样（保留前导 0），用于按 work_id 直接打 ``/api/tracks/{id}``。

        ★ v1.2.3 修复：之前用 ``int(rjcode[2:])`` 会把 ``RJ01337508`` 抹成
        ``1337508``，再拼成 ``/api/tracks/1337508`` 永远 404。kikoeru / asmr.one
        实际接受的 workId 是字符串原样含前导 0（参考 VoiceLinks 油猴脚本
        ``getAsmrOneWorkId``），必须保留 ``01337508`` 这个 8 位字符串。
        """
        normalized = (rjcode or "").upper().strip()
        match = re.match(r"^(RJ|BJ|VJ)(\d{6,8})$", normalized)
        return match.group(2) if match else ""

    def _build_tracks_url_str(self, work_id_str: str) -> str:
        """字符串版 tracks URL，保留前导 0。配合 ``_rjcode_to_work_id_str`` 使用。"""
        return f"{self.config.server_url}/api/tracks/{work_id_str}"
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头，包含 API Token"""
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        if self.config.api_token:
            # 支持 Bearer Token 认证
            headers['Authorization'] = f'Bearer {self.config.api_token}'
            logger.debug("[Kikoeru] 使用 Token 认证: ***")
        else:
            logger.debug("[Kikoeru] 未配置 API Token，使用无认证请求")
        
        return headers

    @staticmethod
    def _safe_headers_for_log(headers: Dict[str, str]) -> Dict[str, str]:
        return sanitize_for_log(dict(headers or {}), max_string=200)

    @staticmethod
    def _compact_response_for_log(data: Any, max_length: int = 1200) -> str:
        text = repr(sanitize_for_log(data, max_string=200))
        if len(text) <= max_length:
            return text
        return text[:max_length] + "...<truncated>"

    def _get_page_headers(self, keyword: str) -> Dict[str, str]:
        headers = {
            **self._get_headers(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Referer': self._build_keyword_works_page_url(keyword),
        }
        return headers

    def _normalize_search_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    def _normalize_title_for_match(self, value: str) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        text = re.sub(r"[\[\(（【].*?[\]\)）】]", " ", text)
        text = re.sub(r"(cv|声優|翻訳|汉化|漢化|中国語版|繁體中文版|繁体中文版|簡体中文版|简体中文版)\s*[:：]?\s*[\w\-\sぁ-んァ-ヶ一-龯]*", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龯]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_title_match_tokens(self, value: str) -> List[str]:
        normalized = self._normalize_title_for_match(value)
        if not normalized:
            return []
        return [token for token in normalized.split(" ") if len(token) >= 2]

    def _rjcode_from_work_id(self, work_id: int) -> str:
        if 0 < work_id < 1_000_000:
            return f"RJ{work_id:06d}"
        if work_id > 0:
            return f"RJ{work_id:08d}"
        return ""

    def _work_to_rjcodes(self, work: Dict) -> List[str]:
        if not isinstance(work, dict):
            return []
        rjcodes: List[str] = []

        def append(value: str) -> None:
            normalized = self._normalize_rjcode(str(value or "").strip()) if str(value or "").strip() else ""
            if re.fullmatch(r"(RJ|BJ|VJ)\d{6,8}", normalized) and normalized not in rjcodes:
                rjcodes.append(normalized)

        try:
            work_id = int(work.get('id') or 0)
        except Exception:
            work_id = 0
        # Kikoeru 的 id 通常就是当前作品 RJ 的数字部分；sourceWorkno 在翻译版上
        # 可能指向原作。先认 id，才能和 VoiceLinks 的关联搜索语义一致。
        append(self._rjcode_from_work_id(work_id))
        for candidate in (
            work.get('sourceWorkno'),
            work.get('source_workno'),
            work.get('workno'),
            work.get('rjcode'),
        ):
            append(candidate)
        return rjcodes

    def _work_to_rjcode(self, work: Dict) -> str:
        rjcodes = self._work_to_rjcodes(work)
        return rjcodes[0] if rjcodes else ""

    def _detect_work_language(self, work: Dict) -> str:
        if not isinstance(work, dict):
            return ""
        tags = work.get('tags', [])
        tag_names = []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict):
                    tag_names.append(str(tag.get('name') or '').strip())
                else:
                    tag_names.append(str(tag or '').strip())
        title = str(work.get('title') or '').strip()
        joined = " ".join([title, *tag_names]).upper()
        if any(token in joined for token in ['CHI_HANS', 'ZH_CN', 'ZH-HANS', '简体', '簡体', '简中']):
            return 'CHI_HANS'
        if any(token in joined for token in ['CHI_HANT', 'ZH_TW', 'ZH-HANT', '繁体', '繁體', '繁中']):
            return 'CHI_HANT'
        if 'ENG' in joined or 'ENGLISH' in joined:
            return 'ENG'
        return ''

    def _extract_total_pages(self, data: dict) -> int:
        pagination = data.get('pagination') if isinstance(data.get('pagination'), dict) else {}
        meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
        total = 0
        for v in (
            data.get('total_pages'),
            data.get('last_page'),
            pagination.get('total_pages'),
            pagination.get('last_page'),
            meta.get('total_pages'),
            meta.get('last_page'),
        ):
            try:
                total = max(total, int(v or 0))
            except Exception:
                pass
        return total

    def _collect_works_unique(self, data: dict, seen_ids: Set[int], out: List[Dict]) -> int:
        works = data.get('works', []) if isinstance(data, dict) else []
        if not isinstance(works, list):
            return 0
        added = 0
        for work in works:
            if not isinstance(work, dict):
                continue
            try:
                wid = int(work.get('id') or 0)
            except Exception:
                wid = 0
            if wid and wid in seen_ids:
                continue
            if wid:
                seen_ids.add(wid)
            out.append(work)
            added += 1
        return added

    def _extract_circle_id_from_work(self, work: Dict) -> int:
        if not isinstance(work, dict):
            return 0
        circle = work.get('circle') if isinstance(work.get('circle'), dict) else {}
        for candidate in (circle.get('id'), work.get('circle_id')):
            try:
                value = int(candidate or 0)
            except Exception:
                value = 0
            if value > 0:
                return value
        return 0

    async def _search_works_by_keyword(self, keyword: str, page: int = 1) -> List[Dict]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        session = await self._get_session()
        headers = self._get_headers()
        url = self._build_keyword_search_url(normalized_keyword, page=page)
        logger.info("[Kikoeru相关翻译补查] 搜索 keyword=%s page=%s", normalized_keyword, page)
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        ) as response:
            if response.status != 200:
                logger.warning("[Kikoeru相关翻译补查] 搜索失败 keyword=%s status=%s", normalized_keyword, response.status)
                return []
            data = await response.json()
        works = data.get('works', []) if isinstance(data, dict) else []
        return works if isinstance(works, list) else []

    async def find_circle_id_by_keyword(self, keyword: str) -> int:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0
        cached_circle_id = self._get_circle_id_cache(normalized_keyword)
        if cached_circle_id > 0:
            return cached_circle_id

        normalized_query = self._normalize_search_text(normalized_keyword)
        best_circle_id = 0
        try:
            for page in range(1, 4):
                works = await self._search_works_by_keyword(normalized_keyword, page=page)
                if not works:
                    break
                for work in works:
                    if not isinstance(work, dict):
                        continue
                    circle = work.get('circle') if isinstance(work.get('circle'), dict) else {}
                    circle_name = str(circle.get('name') or '').strip()
                    circle_id = self._extract_circle_id_from_work(work)
                    if circle_id <= 0:
                        continue
                    if not circle_name:
                        if best_circle_id <= 0:
                            best_circle_id = circle_id
                        continue

                    normalized_circle_name = self._normalize_search_text(circle_name)
                    if normalized_circle_name == normalized_query:
                        self._set_circle_id_cache(normalized_keyword, circle_id)
                        return circle_id
                    if normalized_query and (
                        normalized_query in normalized_circle_name
                        or normalized_circle_name in normalized_query
                    ):
                        if best_circle_id <= 0:
                            best_circle_id = circle_id
        except Exception as exc:
            logger.warning("[Kikoeru] 社团 id 探测失败 keyword=%s error=%s", normalized_keyword, exc)
            return 0

        if best_circle_id > 0:
            self._set_circle_id_cache(normalized_keyword, best_circle_id)
            return best_circle_id
        return 0

    async def list_circle_works(self, circle_id: int, max_pages: int = 100) -> List[Dict]:
        if not self.config.enabled:
            return []
        try:
            normalized_circle_id = int(circle_id or 0)
        except Exception:
            normalized_circle_id = 0
        if normalized_circle_id <= 0:
            return []
        if not await self._ensure_valid_token():
            return []

        session = await self._get_session()
        headers = self._get_headers()

        async def _fetch_page(page: int) -> Optional[dict]:
            url = self._build_circle_works_url(normalized_circle_id, page=page)
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("[Kikoeru] 社团直连拉取失败 circle_id=%s page=%s status=%s", normalized_circle_id, page, resp.status)
                        return None
                    return await resp.json()
            except Exception as exc:
                logger.warning("[Kikoeru] 社团直连拉取异常 circle_id=%s page=%s error=%s", normalized_circle_id, page, exc)
                return None

        all_works: List[Dict] = []
        seen_ids: Set[int] = set()
        data1 = await _fetch_page(1)
        if not data1:
            return all_works
        self._collect_works_unique(data1, seen_ids, all_works)
        total_pages = self._extract_total_pages(data1)
        if total_pages <= 0:
            total_pages = max_pages
        effective_max = min(total_pages, max(1, int(max_pages)))
        if effective_max <= 1:
            return all_works

        batch_size = 5
        for batch_start in range(2, effective_max + 1, batch_size):
            pages = list(range(batch_start, min(batch_start + batch_size, effective_max + 1)))
            results = await asyncio.gather(*[_fetch_page(p) for p in pages], return_exceptions=True)
            for res in results:
                if isinstance(res, Exception) or res is None:
                    continue
                self._collect_works_unique(res, seen_ids, all_works)

        logger.info("[Kikoeru] 社团直连拉取完成 circle_id=%s works=%d effective_max_pages=%d", normalized_circle_id, len(all_works), effective_max)
        return all_works

    async def _find_related_translation_candidates(
        self,
        requested_rjcode: str,
        linked_works: Dict[str, any],
    ) -> Dict[str, KikoeruCheckResult]:
        dlsite_service = get_dlsite_service()
        requested_work = linked_works.get(requested_rjcode)
        requested_lang = str(getattr(requested_work, 'lang', '') or '').upper()
        requested_type = str(getattr(requested_work, 'work_type', '') or '').strip().lower()
        if requested_lang not in {'CHI_HANS', 'CHI_HANT', 'ENG'}:
            return {}
        if requested_type not in {'translation', 'child_translation'}:
            return {}

        try:
            product_info = await dlsite_service.get_product_info(requested_rjcode)
        except Exception as exc:
            logger.warning("[Kikoeru相关翻译补查] 获取作品信息失败 %s: %s", requested_rjcode, exc)
            return {}
        if not product_info or not product_info.get('product'):
            return {}

        product = dict(product_info.get('product') or {})
        translation_info = dict(product.get('translation_info') or {})
        original_workno = self._normalize_rjcode(
            translation_info.get('original_workno')
            or translation_info.get('parent_workno')
            or ''
        )
        original_title = ""
        if original_workno and original_workno != requested_rjcode:
            try:
                original_product_info = await dlsite_service.get_product_info(original_workno)
                original_title = str(((original_product_info or {}).get('product') or {}).get('work_name') or '').strip()
            except Exception as exc:
                logger.warning("[Kikoeru相关翻译补查] 获取原作信息失败 %s: %s", original_workno, exc)

        requested_title = str(product.get('work_name') or '').strip()
        keyword_candidates: List[str] = []
        for candidate in [requested_title, original_title]:
            normalized = self._normalize_title_for_match(candidate)
            if normalized and normalized not in keyword_candidates:
                keyword_candidates.append(normalized)
        if not keyword_candidates:
            return {}

        target_texts = [self._normalize_title_for_match(requested_title)]
        if original_title:
            target_texts.append(self._normalize_title_for_match(original_title))
        target_tokens = set()
        for text in [requested_title, original_title]:
            target_tokens.update(self._extract_title_match_tokens(text))
        if not target_tokens:
            return {}

        matched_results: Dict[str, KikoeruCheckResult] = {}
        seen_candidate_rjcodes: Set[str] = set()
        session = await self._get_session()
        headers = self._get_headers()

        for keyword in keyword_candidates[:2]:
            try:
                works = await self._search_works_by_keyword(keyword, page=1)
            except Exception as exc:
                logger.warning("[Kikoeru相关翻译补查] 搜索异常 keyword=%s error=%s", keyword, exc)
                continue

            for work in works[:20]:
                candidate_rjcode = self._work_to_rjcode(work)
                if not candidate_rjcode or candidate_rjcode in seen_candidate_rjcodes:
                    continue
                seen_candidate_rjcodes.add(candidate_rjcode)
                if candidate_rjcode == requested_rjcode or candidate_rjcode in linked_works:
                    continue

                candidate_lang = self._detect_work_language(work)
                if candidate_lang and candidate_lang != requested_lang:
                    continue

                candidate_title = str(work.get('title') or '').strip()
                normalized_candidate_title = self._normalize_title_for_match(candidate_title)
                if not normalized_candidate_title:
                    continue

                similarity = max(
                    [difflib.SequenceMatcher(None, normalized_candidate_title, text).ratio() for text in target_texts if text] or [0.0]
                )
                overlap = len(set(self._extract_title_match_tokens(candidate_title)) & target_tokens)
                if similarity < 0.72 and overlap < max(2, min(4, len(target_tokens))):
                    continue

                result = KikoeruCheckResult(
                    is_found=True,
                    rjcode=requested_rjcode,
                    work_id=int(work.get('id') or 0),
                    title=candidate_title,
                    circle_name=str((work.get('circle') or {}).get('name') or ''),
                    tags=[str(tag.get('name') or '') for tag in (work.get('tags') or []) if isinstance(tag, dict)],
                    total_count=1,
                    source="kikoeru_related_translation",
                    match_type="related_translation",
                    matched_rjcode=candidate_rjcode,
                )
                result = await self._hydrate_track_subtitle_state(result, session, headers)
                matched_results[candidate_rjcode] = result
                logger.info(
                    "[Kikoeru相关翻译补查] 命中 requested=%s candidate=%s similarity=%.3f overlap=%s title=%s",
                    requested_rjcode,
                    candidate_rjcode,
                    similarity,
                    overlap,
                    candidate_title,
                )
        return matched_results

    def _is_subtitle_track_file(self, item: Dict) -> bool:
        if not isinstance(item, dict):
            return False
        if str(item.get('type') or '').strip().lower() != 'text':
            return False

        title = str(item.get('title') or '').strip()
        if not title:
            return False

        ext = title.rsplit('.', 1)[-1].lower() if '.' in title else ''
        if f'.{ext}' not in {'.lrc', '.vtt', '.srt', '.ass', '.ssa'}:
            return False

        has_real_file_field = any(
            str(item.get(key) or '').strip()
            for key in ('hash', 'mediaDownloadUrl', 'media_download_url', 'mediaStreamUrl', 'media_stream_url')
        )
        return has_real_file_field

    def _count_subtitle_files_from_tracks(self, entries) -> int:
        count = 0

        def walk(nodes):
            nonlocal count
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if self._is_subtitle_track_file(node):
                    count += 1
                children = node.get('children')
                if isinstance(children, list) and children:
                    walk(children)

        walk(entries)
        return count

    def _count_all_files_from_tracks(self, entries) -> int:
        """统计文件树中所有文件节点数量（不含目录），用于检测空壳作品。"""
        count = 0

        def walk(nodes):
            nonlocal count
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = str(node.get('type') or '').lower()
                if node_type == 'file' or (node_type != 'folder' and node.get('hash')):
                    count += 1
                children = node.get('children')
                if isinstance(children, list) and children:
                    walk(children)

        walk(entries)
        return count

    async def _fetch_track_subtitle_state(
        self,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
        work_id: int,
    ) -> tuple[Optional[int], str]:
        if not work_id:
            return None, None, "work_id_empty"

        url = self._build_tracks_url(work_id)
        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as response:
                if response.status != 200:
                    logger.warning("[Kikoeru] 获取作品文件树失败: work_id=%s status=%s", work_id, response.status)
                    return None, None, f"tracks_http_{response.status}"
                data = await response.json()
                subtitle_count = self._count_subtitle_files_from_tracks(data)
                total_count = self._count_all_files_from_tracks(data)
                logger.info("[Kikoeru] 作品文件树字幕统计: work_id=%s subtitle_count=%s total_count=%s", work_id, subtitle_count, total_count)
                return subtitle_count, total_count, "tracks"
        except Exception as exc:
            logger.warning("[Kikoeru] 获取作品文件树异常: work_id=%s error=%s", work_id, exc)
            return None, None, "tracks_error"

    async def _hydrate_track_subtitle_state(
        self,
        result: KikoeruCheckResult,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
    ) -> KikoeruCheckResult:
        if not result.is_found or not result.work_id:
            return result

        # ★ v1.2.3：优先用 RJ 号转出来的字符串 work_id（保留前导 0）打 tracks 接口，
        # 避免 int(work_id) 把 ``RJ01337508`` 抹成 ``1337508`` 导致 ``/api/tracks/1337508`` 404。
        # matched_rjcode 是 _normalize_rjcode 后的结果（含 RJ 前缀 + 原始位数）。
        rj_for_tracks = result.matched_rjcode or result.rjcode
        work_id_str = self._rjcode_to_work_id_str(rj_for_tracks)

        if work_id_str:
            url = self._build_tracks_url_str(work_id_str)
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "[Kikoeru] hydrate tracks 失败: rjcode=%s url=%s status=%s",
                            rj_for_tracks, url, response.status,
                        )
                        result.subtitle_check_source = f"tracks_http_{response.status}"
                        return result
                    data = await response.json()
                    subtitle_count = self._count_subtitle_files_from_tracks(data)
                    total_count = self._count_all_files_from_tracks(data)
                    result.subtitle_file_count = int(subtitle_count or 0)
                    result.total_track_count = int(total_count if total_count is not None else -1)
                    result.subtitle_check_source = "tracks"
                    result.has_lyric_hint = bool(subtitle_count and subtitle_count > 0)
                    return result
            except Exception as exc:
                logger.warning(
                    "[Kikoeru] hydrate tracks 异常: rjcode=%s url=%s error=%s",
                    rj_for_tracks, url, exc,
                )
                result.subtitle_check_source = "tracks_error"
                return result

        # 兜底：RJ 号没法解析出 work_id_str（理论上不会走到），退回老 int 路径
        subtitle_count, total_count, source = await self._fetch_track_subtitle_state(session, headers, result.work_id)
        if subtitle_count is None:
            result.subtitle_check_source = source
            return result

        result.subtitle_file_count = int(subtitle_count)
        result.total_track_count = int(total_count if total_count is not None else -1)
        result.subtitle_check_source = source
        result.has_lyric_hint = subtitle_count > 0
        return result

    async def _probe_work_by_id(
        self,
        rjcode: str,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
    ) -> Optional[KikoeruCheckResult]:
        """search 未命中时的硬兜底：按 RJ 号推 work_id，直接打 ``/api/tracks/{id}``。

        ★ 用户反馈痛点（v1.2.2 修复 / v1.2.3 进一步修正）：RJ01304475 这类作品在
        kikoeru 网页上能搜到，但 ``/api/search?keyword=RJ01304475`` 返回的
        ``works`` 数组里没有它。原因是部分 kikoeru 部署的 search 全文索引对带
        前缀 0 的新作 RJ 号 / 翻译版的 sourceWorkno 索引会漂移漏掉，但
        ``/api/tracks/{work_id}`` 这条按主键拿 work 文件树的路由是稳定的，
        ``200`` 即代表 work 存在。

        ★ v1.2.3 关键修复：work_id 用 ``_rjcode_to_work_id_str`` 取**字符串原样**
        （保留前导 0），不能再走 ``_rjcode_to_id`` 的 int 转换，否则 ``RJ01337508``
        会被抹成 ``1337508``，拼出来的 ``/api/tracks/1337508`` 永远 404，整个
        兜底就废了（参考 VoiceLinks 油猴脚本 ``getAsmrOneWorkId`` 的实现）。

        本方法把 RJ 号截掉前缀作为字符串 work_id 直接 GET tracks，命中即视为
        作品存在并构造一个 ``is_found=True`` 的结果（同时填好字幕统计字段）。
        """
        work_id_str = self._rjcode_to_work_id_str(rjcode)
        if not work_id_str:
            return None

        url = self._build_tracks_url_str(work_id_str)
        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as response:
                logger.info(
                    "[Kikoeru] tracks 兜底探测: rjcode=%s work_id_str=%s url=%s status=%s",
                    rjcode, work_id_str, url, response.status,
                )
                if response.status != 200:
                    return None
                data = await response.json()
                subtitle_count = self._count_subtitle_files_from_tracks(data)
                total_count = self._count_all_files_from_tracks(data)
        except Exception as exc:
            logger.warning(
                "[Kikoeru] tracks 兜底请求异常: rjcode=%s work_id_str=%s error=%s",
                rjcode, work_id_str, exc,
            )
            return None

        # work_id 字段保留 int 形式以兼容下游（KikoeruCheckResult.work_id 类型为 int）。
        # 这里用 int 转换不影响后续判断，因为兜底命中后不会再用 work_id 拼 URL。
        try:
            work_id_int = int(work_id_str)
        except ValueError:
            work_id_int = 0

        result = KikoeruCheckResult(
            rjcode=rjcode,
            is_found=True,
            work_id=work_id_int,
            matched_rjcode=self._normalize_rjcode(rjcode),
            match_type="direct_work_id",
            source="kikoeru_tracks_probe",
            subtitle_file_count=int(subtitle_count or 0),
            total_track_count=int(total_count if total_count is not None else -1),
            subtitle_check_source="tracks_probe",
            has_lyric_hint=bool(subtitle_count and subtitle_count > 0),
        )
        return result
    
    async def check_duplicate(
        self,
        rjcode: str,
        use_cache: bool = True,
        extra_match_rjcodes: Optional[Set[str]] = None,
    ) -> KikoeruCheckResult:
        normalized_rjcode = self._normalize_rjcode(rjcode)
        extra_key = tuple(sorted(
            self._normalize_rjcode(item)
            for item in (extra_match_rjcodes or set())
            if str(item or "").strip()
        ))
        inflight_key = (normalized_rjcode, bool(use_cache), extra_key)
        existing = self._duplicate_inflight.get(inflight_key)
        if existing is not None and not existing.done():
            logger.debug("[Kikoeru] 复用进行中的查重请求: rj=%s extra=%s", normalized_rjcode, len(extra_key))
            return await asyncio.shield(existing)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._duplicate_inflight[inflight_key] = future
        try:
            result = await self._check_duplicate_impl(
                normalized_rjcode,
                use_cache=use_cache,
                extra_match_rjcodes=set(extra_key) if extra_key else extra_match_rjcodes,
            )
            if not future.done():
                future.set_result(result)
            return result
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                future.add_done_callback(lambda item: item.exception())
            raise
        finally:
            if self._duplicate_inflight.get(inflight_key) is future:
                self._duplicate_inflight.pop(inflight_key, None)

    async def _check_duplicate_impl(
        self,
        rjcode: str,
        use_cache: bool = True,
        extra_match_rjcodes: Optional[Set[str]] = None,
    ) -> KikoeruCheckResult:
        """检查作品是否在 Kikoeru 服务器中。

        Args:
            rjcode: RJ号 (格式: RJ123456 或 123456)
            use_cache: 是否使用缓存
            extra_match_rjcodes: 可选关联 RJ 集合（一般来自 DLsite 完整关联链）。
                若严格匹配未命中，会让 ``_parse_search_result`` 退而求其次，把
                返回的某个 work 的候选 RJ 命中本集合视为命中（``match_type``
                标为 ``linkage_match``）。修复 RJ01407907 类痛点：原作没有上
                Kikoeru 但简中翻译版上了，搜原作时被 Kikoeru 直接返回翻译版
                却被严格匹配漏掉。

        Returns:
            KikoeruCheckResult: 查重结果
        """
        rjcode = self._normalize_rjcode(rjcode)
        has_linkage_context = bool(extra_match_rjcodes)

        if use_cache:
            cached = self._get_cache(rjcode)
            if cached:
                # 严格命中或不需要广义匹配的调用方，直接复用缓存即可。
                # 反之（缓存为未命中且当前调用方提供了关联链），跳过缓存重新查询，
                # 给广义匹配一次机会，避免被 5 分钟内的旧"未命中"卡死。
                if cached.is_found or not has_linkage_context:
                    logger.debug(f"Kikoeru 查重缓存命中: {rjcode}")
                    return cached
                # ★ 性能优化：cache 是"未命中"且本次提供了关联链——之前会跳过 cache
                # 重新打 search，但 search keyword 是 RJ 号，response 不会因 linkage
                # 上下文而变。先尝试复用 raw response 重新 _parse_search_result（CPU 操作），
                # 给广义匹配一次机会而不必触网。raw 也没缓存才 fall through 到 HTTP。
                cached_raw = self._search_response_cache.get(rjcode)
                if cached_raw is not None:
                    raw_data, _raw_ts = cached_raw
                    logger.debug(
                        "[Kikoeru] 缓存为未命中但 raw response 仍在缓存，复用 raw 重 parse 给广义匹配: %s",
                        rjcode,
                    )
                    session = await self._get_session()
                    headers = self._get_headers()
                    result = self._parse_search_result(
                        rjcode, raw_data, extra_match_rjcodes=extra_match_rjcodes
                    )
                    if result.is_found:
                        # raw 复用的广义命中需要补全 tracks subtitle 状态（依赖 HTTP 但只 1 次 GET）。
                        result = await self._hydrate_track_subtitle_state(result, session, headers)
                        self._maybe_cache_result(rjcode, result, use_cache)
                        return result
                    # 复用 raw 重 parse 后仍未命中：返回 cached（含 work_id 兜底已尝试过的状态），
                    # 不再触网。
                    return cached
                logger.debug(
                    "[Kikoeru] 缓存为未命中，本次提供了关联链且 raw 也已过期，重新 search 尝试广义匹配: %s",
                    rjcode,
                )

        if not self.config.enabled or not self.config.server_url:
            return KikoeruCheckResult(
                is_found=False,
                rjcode=rjcode,
                source="kikoeru_disabled"
            )

        if not await self._ensure_valid_token():
            if not self.config.api_token:
                logger.warning("[Kikoeru] 无法获取有效 Token")
                return KikoeruCheckResult(
                    is_found=False,
                    rjcode=rjcode,
                    source="kikoeru_no_token"
                )

        try:
            url = self._build_search_url(rjcode)
            headers = self._get_headers()

            session = await self._get_session()

            logger.debug("[Kikoeru] 正在查询: %s", rjcode)
            logger.debug("[Kikoeru] 请求 URL: %s", mask_url_for_log(url))
            logger.debug("[Kikoeru] 请求头: %s", self._safe_headers_for_log(headers))

            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as response:
                logger.debug(f"[Kikoeru] 响应状态: {response.status}")

                if response.status == 401:
                    error_text = sanitize_text_for_log(await response.text(), max_length=500)
                    logger.warning(f"[Kikoeru] Token 过期或无效，尝试重新登录: {rjcode}")

                    if self.config.username and self.config.password:
                        if await self._login():
                            headers = self._get_headers()
                            async with session.get(
                                url,
                                headers=headers,
                                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                            ) as retry_response:
                                if retry_response.status == 200:
                                    data = await retry_response.json()
                                    # ★ 写 raw response cache（401 重登路径），
                                    # 后续同 RJ 带新 linkage 进来时可复用 raw 重 parse 不重新 search。
                                    self._search_response_cache[rjcode] = (data, datetime.now())
                                    result = self._parse_search_result(
                                        rjcode, data, extra_match_rjcodes=extra_match_rjcodes
                                    )
                                    result = await self._hydrate_track_subtitle_state(result, session, headers)
                                    # 401 重登路径同样接 work_id 兜底
                                    if not result.is_found:
                                        direct_hit = await self._probe_work_by_id(rjcode, session, headers)
                                        if direct_hit and direct_hit.is_found:
                                            logger.info(
                                                "[Kikoeru] ✓ 401 重登后 search 未命中但 tracks 直接命中: %s -> work_id=%s",
                                                rjcode, direct_hit.work_id,
                                            )
                                            if use_cache:
                                                self._set_cache(rjcode, direct_hit)
                                            return direct_hit
                                    self._maybe_cache_result(rjcode, result, use_cache)
                                    return result

                    logger.error(f"[Kikoeru] 认证失败: {rjcode}")
                    logger.debug("[Kikoeru] 认证失败响应内容: %s", error_text)
                    return KikoeruCheckResult(
                        is_found=False,
                        rjcode=rjcode,
                        source="kikoeru_auth_error"
                    )

                if response.status != 200:
                    error_text = sanitize_text_for_log(await response.text(), max_length=500)
                    logger.warning(f"[Kikoeru] 服务器返回错误: rj={rjcode} status={response.status}")
                    logger.debug("[Kikoeru] 错误响应: %s", error_text)
                    return KikoeruCheckResult(
                        is_found=False,
                        rjcode=rjcode,
                        source=f"kikoeru_error_{response.status}"
                    )

                data = await response.json()
                logger.debug("[Kikoeru] 响应数据: %s", self._compact_response_for_log(data))
                # ★ 写 raw response cache（正常路径），下次同 RJ 带新 linkage 进来
                # 时可复用 raw 重 parse 不重新 search。
                self._search_response_cache[rjcode] = (data, datetime.now())

                result = self._parse_search_result(
                    rjcode, data, extra_match_rjcodes=extra_match_rjcodes
                )
                result = await self._hydrate_track_subtitle_state(result, session, headers)

                if not result.is_found:
                    # ★ 硬兜底：search 没命中时，按 work_id 直接打 /api/tracks/{id}。
                    #   修复 v1.2.2 用户痛点：kikoeru 网页能搜到但 API search 漏返回。
                    direct_hit = await self._probe_work_by_id(rjcode, session, headers)
                    if direct_hit and direct_hit.is_found:
                        logger.info(
                            "[Kikoeru] ✓ search 未命中但 tracks 接口直接命中: %s -> work_id=%s subtitle=%s",
                            rjcode, direct_hit.work_id, direct_hit.subtitle_file_count,
                        )
                        if use_cache:
                            self._set_cache(rjcode, direct_hit)
                        return direct_hit

                    if self.config.enable_fuzzy_rj_match:
                        logger.warning(f"[Kikoeru] 精确匹配未找到，已启用危险的宽容搜索（±1）: {rjcode}")
                        fuzzy_result = await self._check_fuzzy(rjcode, session, headers, use_cache)
                        if fuzzy_result.is_found:
                            logger.warning(f"[Kikoeru] ✓ 宽容匹配成功: {rjcode} -> {fuzzy_result.matched_rjcode}")
                            return fuzzy_result
                    else:
                        logger.info(f"[Kikoeru] 精确匹配未找到，已跳过 ±1 宽容搜索: {rjcode}")

                self._maybe_cache_result(rjcode, result, use_cache)

                if result.is_found:
                    if result.match_type == "linkage_match":
                        logger.info(
                            "[Kikoeru] ✓ 关联链广义命中: %s -> %s (work_id=%s title=%s)",
                            rjcode, result.matched_rjcode, result.work_id, result.title,
                        )
                    else:
                        logger.info(f"[Kikoeru] ✓ 精确匹配成功: {rjcode} - {result.title}")
                else:
                    if self.config.enable_fuzzy_rj_match:
                        logger.info(f"[Kikoeru] ✗ 未找到: {rjcode}（包括±1宽容搜索）")
                    else:
                        logger.info(f"[Kikoeru] ✗ 未找到: {rjcode}（仅精确匹配）")

                return result
                
        except asyncio.TimeoutError:
            logger.warning(f"Kikoeru 服务器查询超时: {rjcode}")
            return KikoeruCheckResult(
                is_found=False,
                rjcode=rjcode,
                source="kikoeru_timeout"
            )
        except Exception as e:
            logger.error(f"Kikoeru 服务器查询失败: {rjcode}, 错误: {e}")
            return KikoeruCheckResult(
                is_found=False,
                rjcode=rjcode,
                source="kikoeru_exception"
            )
    
    def _normalize_rjcode(self, rjcode: str) -> str:
        """标准化 RJ 号"""
        rjcode = rjcode.upper().strip()
        if not rjcode.startswith('RJ') and not rjcode.startswith('BJ') and not rjcode.startswith('VJ'):
            rjcode = 'RJ' + rjcode
        return rjcode
    
    async def _check_fuzzy(
        self, 
        rjcode: str, 
        session: aiohttp.ClientSession, 
        headers: Dict[str, str],
        use_cache: bool
    ) -> KikoeruCheckResult:
        """
        宽容搜索：尝试 RJ 号 ±1
        
        Args:
            rjcode: 原始 RJ 号
            session: HTTP Session
            headers: 请求头
            use_cache: 是否使用缓存
        
        Returns:
            KikoeruCheckResult: 查重结果（包含模糊匹配信息）
        """
        # 提取数字部分
        import re
        match = re.match(r'(RJ|BJ|VJ)(\d+)', rjcode.upper())
        if not match:
            return KikoeruCheckResult(rjcode=rjcode)
        
        prefix = match.group(1)
        num = int(match.group(2))
        
        # 尝试 ±1
        for delta in [-1, 1]:
            fuzzy_num = num + delta
            if fuzzy_num < 0:
                continue
            
            # 构建模糊 RJ 号（保持相同位数）
            original_len = len(match.group(2))
            fuzzy_rjcode = f"{prefix}{fuzzy_num:0{original_len}d}"
            
            try:
                url = self._build_search_url(fuzzy_rjcode)
                logger.info(f"[Kikoeru] 尝试模糊匹配: {fuzzy_rjcode}")
                
                async with session.get(
                    url, 
                    headers=headers, 
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = self._parse_search_result(fuzzy_rjcode, data)
                        
                        if result.is_found:
                            # 找到模糊匹配
                            result.rjcode = rjcode  # 保持原始 RJ 号
                            result.match_type = "fuzzy"
                            result.matched_rjcode = fuzzy_rjcode
                            result.tolerance = delta
                            
                            if use_cache:
                                self._set_cache(rjcode, result)
                            
                            logger.info(f"[Kikoeru] 模糊匹配成功: {rjcode} -> {fuzzy_rjcode}")
                            return result
                            
            except Exception as e:
                logger.debug(f"[Kikoeru] 模糊匹配失败 {fuzzy_rjcode}: {e}")
                continue
        
        # 未找到模糊匹配
        return KikoeruCheckResult(rjcode=rjcode)
    
    def _fill_result_from_work(
        self,
        result: KikoeruCheckResult,
        work: Dict,
        matched_rjcode: str,
        match_type: str,
    ) -> None:
        """把 Kikoeru search 命中的 work 字段灌入查重结果对象。

        统一逻辑给严格命中与 linkage 广义命中复用，避免拷贝粘贴漂移。
        """
        result.is_found = True
        result.work_id = int(work.get('id') or 0)
        result.title = str(work.get('title') or '')
        result.lyric_status = str(work.get('lyric_status', '') or '')
        result.has_lyric_hint = False
        result.subtitle_file_count = 0
        result.subtitle_check_source = "search_only"
        result.matched_rjcode = matched_rjcode
        result.match_type = match_type

        circle = work.get('circle', {})
        if isinstance(circle, dict):
            result.circle_name = str(circle.get('name') or '')

        tags = work.get('tags', [])
        if isinstance(tags, list):
            result.tags = [str(tag.get('name') or '') for tag in tags if isinstance(tag, dict)]

    def _parse_search_result(
        self,
        rjcode: str,
        data: dict,
        extra_match_rjcodes: Optional[Set[str]] = None,
    ) -> KikoeruCheckResult:
        """解析 Kikoeru 搜索结果。

        ★ 关键修复（RJ01407907 类痛点）：当 ``extra_match_rjcodes`` 非空（一般是
        DLsite 完整关联链），严格 1:1 匹配未命中时，会做第二轮"广义关联匹配"——
        只要返回的某个 work 的候选 RJ 落在关联链里就算命中。这对应了油猴脚本
        ``getKikoeruSearchResult`` 里 ``linkages[rj]`` 的语义：搜原作 RJ 时
        Kikoeru 实际可能只回简中翻译版 work（``id`` 是翻译版 RJ 的数字部分，
        且没有 sourceWorkno 字段），严格匹配会漏掉，导致整条链路误报未命中。
        """
        result = KikoeruCheckResult(rjcode=rjcode)

        # 检查是否有 works 字段
        if not isinstance(data, dict) or 'works' not in data:
            logger.warning(f"Kikoeru 返回格式异常: {rjcode}")
            return result

        works = data.get('works', [])
        if not isinstance(works, list):
            return result

        result.total_count = len(works)

        # 查找匹配的作品。
        # 不能只看 id：不同部署 / 数据源下，搜索结果里更稳定的主键有时是
        # sourceWorkno/source_workno/workno/rjcode。
        search_id = self._rjcode_to_id(rjcode)
        normalized_target_rjcode = self._normalize_rjcode(rjcode)

        # 诊断日志：当 works 非空但最终 not found 时，能从日志立即看出每个候选 work
        # 的 id / sourceWorkno / candidate_rjcodes，以及为什么没匹配上。
        # 这是定位"kikoeru 网页搜得到但 backend 报未命中"问题的关键证据链。
        if works:
            preview = []
            for work in works[:5]:
                if not isinstance(work, dict):
                    continue
                preview.append({
                    "id": work.get("id"),
                    "sourceWorkno": work.get("sourceWorkno") or work.get("source_workno"),
                    "workno": work.get("workno") or work.get("rjcode"),
                    "title": (work.get("title") or "")[:60],
                    "candidates": self._work_to_rjcodes(work),
                })
            logger.info(
                "[Kikoeru] search 候选 works (rjcode=%s search_id=%s normalized=%s total=%s preview=%s)",
                rjcode, search_id, normalized_target_rjcode, len(works), preview,
            )

        # ---- 第一轮：严格 1:1 匹配（保留原有行为）----
        for work in works:
            if not isinstance(work, dict):
                continue

            work_id = work.get('id', 0)
            candidate_rjcodes = self._work_to_rjcodes(work)

            # 优先认显式 RJ 字段；没有时再退回 id 数字匹配。
            if normalized_target_rjcode in candidate_rjcodes or work_id == search_id:
                self._fill_result_from_work(result, work, normalized_target_rjcode, match_type="exact")
                return result

        # ---- 第二轮：linkage 广义匹配（新增）----
        # 仅当调用方提供了 DLsite 关联链才启用。这样不会改变无上下文调用方
        # 的语义。匹配命中后 ``matched_rjcode`` 会指向真正存在于 Kikoeru
        # 的关联 RJ（多半是某个翻译版），后续 hydrate 会按这个 RJ 拼 tracks URL。
        if extra_match_rjcodes:
            normalized_extra: Set[str] = set()
            for rj in extra_match_rjcodes:
                normalized = self._normalize_rjcode(rj or '')
                if normalized:
                    normalized_extra.add(normalized)
            # 主查询 RJ 已经在第一轮处理过；从扩展集合里剔掉避免误报为广义命中
            normalized_extra.discard(normalized_target_rjcode)

            if normalized_extra:
                for work in works:
                    if not isinstance(work, dict):
                        continue
                    candidate_rjcodes = self._work_to_rjcodes(work)
                    matched_linkage_rjcode = next(
                        (rj for rj in candidate_rjcodes if rj in normalized_extra),
                        None,
                    )
                    if matched_linkage_rjcode:
                        self._fill_result_from_work(
                            result,
                            work,
                            matched_linkage_rjcode,
                            match_type="linkage_match",
                        )
                        logger.info(
                            "[Kikoeru] ✓ linkage 广义命中: query=%s matched=%s work_id=%s candidates=%s",
                            normalized_target_rjcode,
                            matched_linkage_rjcode,
                            work.get('id'),
                            candidate_rjcodes,
                        )
                        return result

        return result
    
    def _rjcode_to_id(self, rjcode: str) -> int:
        """将 RJ 号转换为 Kikoeru 的 ID"""
        # 去掉前缀，转换为整数
        # RJ01011249 -> 1011249
        # RJ123456 -> 123456
        rjcode = rjcode.upper()
        for prefix in ['RJ', 'BJ', 'VJ']:
            if rjcode.startswith(prefix):
                try:
                    return int(rjcode[len(prefix):])
                except ValueError:
                    return 0
        return 0
    
    async def check_duplicates_batch(
        self,
        rjcodes: List[str],
        use_cache: bool = True,
        extra_match_rjcodes: Optional[Set[str]] = None,
    ) -> Dict[str, KikoeruCheckResult]:
        """批量检查多个 RJ 号。

        Args:
            rjcodes: RJ 号列表
            use_cache: 是否使用缓存
            extra_match_rjcodes: 透传给 ``check_duplicate`` 的关联链集合，
                让批量内每个查询都能识别返回里的关联翻译版（参考
                ``check_duplicate`` 文档）。

        Returns:
            Dict[str, KikoeruCheckResult]: RJ号到结果的映射
        """
        if not self.config.enabled:
            return {rj: KikoeruCheckResult(is_found=False, rjcode=rj, source="kikoeru_disabled") 
                    for rj in rjcodes}

        tasks = [
            self.check_duplicate(rj, use_cache, extra_match_rjcodes=extra_match_rjcodes)
            for rj in rjcodes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            rj: result if not isinstance(result, Exception) else KikoeruCheckResult(
                is_found=False, 
                rjcode=rj, 
                source="kikoeru_exception"
            )
            for rj, result in zip(rjcodes, results)
        }
    
    async def test_connection(self) -> Dict[str, any]:
        """
        测试与 Kikoeru 服务器的连接
        
        Returns:
            Dict: 包含 success, message, latency 等信息
        """
        if not self.config.enabled:
            return {
                'success': False,
                'message': 'Kikoeru 服务器查重未启用',
                'latency': 0
            }
        
        if not self.config.server_url:
            return {
                'success': False,
                'message': 'Kikoeru 服务器 URL 未配置',
                'latency': 0
            }
        
        start_time = datetime.now()
        
        try:
            if not await self._ensure_valid_token():
                if not self.config.api_token:
                    return {
                        'success': False,
                        'message': '无法获取有效的认证 Token，请检查用户名和密码',
                        'latency': 0
                    }
            
            test_rjcode = "RJ123456"
            url = self._build_search_url(test_rjcode)
            headers = self._get_headers()
            
            session = await self._get_session()
            
            async with session.get(
                url, 
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            ) as response:
                latency = (datetime.now() - start_time).total_seconds() * 1000
                
                if response.status == 200:
                    return {
                        'success': True,
                        'message': f'连接成功 (延迟: {latency:.0f}ms)',
                        'latency': latency,
                        'status_code': response.status
                    }
                elif response.status == 401:
                    return {
                        'success': False,
                        'message': '认证失败，请检查用户名和密码',
                        'latency': latency,
                        'status_code': response.status
                    }
                else:
                    return {
                        'success': False,
                        'message': f'服务器返回错误: {response.status}',
                        'latency': latency,
                        'status_code': response.status
                    }
                    
        except asyncio.TimeoutError:
            latency = (datetime.now() - start_time).total_seconds() * 1000
            return {
                'success': False,
                'message': f'连接超时 ({self.config.timeout}秒)',
                'latency': latency
            }
        except Exception as e:
            latency = (datetime.now() - start_time).total_seconds() * 1000
            return {
                'success': False,
                'message': f'连接失败: {str(e)}',
                'latency': latency
            }
    
    def _normalize_lang_code(self, lang: str) -> str:
        """将 DLsite 语言代码转换为标准格式"""
        lang_map = {
            'JPN': 'JPN',
            'CHN': 'CHI_HANS',  # 简体中文
            'TWN': 'CHI_HANT',  # 繁体中文
            'ENG': 'ENG',
            'KOR': 'KOR',
        }
        return lang_map.get(lang.upper(), lang.upper())

    async def check_duplicate_with_linkages(
        self,
        rjcode: str,
        cue_languages: List[str] = None,
        use_cache: bool = True
    ) -> Dict[str, KikoeruCheckResult]:
        """检查作品及其关联作品是否在 Kikoeru 服务器中。

        关联作品查重逻辑：
        - 如果 Kikoeru 中有原版，当前是翻译版 → 算重复
        - 如果 Kikoeru 中有翻译版，当前是原版 → 算重复
        - 如果 Kikoeru 中有任何关联作品 → 算重复

        ★ 链路上下文：先从 DLsite 取完整关联链，再把完整 RJ 集合作为
        ``extra_match_rjcodes`` 透传给所有 Kikoeru 查询。这样即使 Kikoeru 的
        全文搜索对原作 RJ 的响应只回了一条简中翻译版（``id`` 是翻译 RJ 的
        数字部分、且没有 ``sourceWorkno`` 字段），``_parse_search_result``
        也能把它识别为关联链命中（``match_type='linkage_match'``）。这是修复
        RJ01407907 这类用户痛点（图二报"整条链路未命中"，但 view.txt 油猴
        脚本 ``getKikoeruSearchResult`` 能命中）的关键路径。

        Args:
            rjcode: RJ号
            cue_languages: 需要检查的语言列表（已弃用，现在查询所有关联作品）
            use_cache: 是否使用缓存

        Returns:
            Dict[str, KikoeruCheckResult]: 所有关联作品及其查重结果
        """
        rjcode = self._normalize_rjcode(rjcode)
        results: Dict[str, KikoeruCheckResult] = {}

        if not self.config.enabled:
            # 服务未启用：直接退化为单次查询，不再触发 DLsite 链路与广义匹配。
            primary_result = await self.check_duplicate(rjcode, use_cache)
            results[rjcode] = primary_result
            return results

        # 1. 先尝试取 DLsite 完整关联链——必须在主查询之前，这样主查询也能
        #    带着完整链路去识别 Kikoeru 返回里的关联翻译版。
        linked_works: Dict[str, any] = {}
        try:
            logger.info(f"[Kikoeru关联查询] 开始获取 {rjcode} 的关联作品")
            dlsite_service = get_dlsite_service()
            linked_works = await dlsite_service.get_linked_works(rjcode) or {}
        except Exception as e:
            logger.warning("[Kikoeru关联查询] 获取关联作品失败 %s: %s", rjcode, e)
            linked_works = {}

        # 把链路展开成已规范化的 RJ 集合（含主 RJ 自身），供广义匹配使用。
        linkage_rjcode_set: Set[str] = set()
        for workno in linked_works.keys():
            normalized = self._normalize_rjcode(workno or '')
            if normalized:
                linkage_rjcode_set.add(normalized)
        if rjcode:
            linkage_rjcode_set.add(rjcode)
        extra_for_lookup: Optional[Set[str]] = linkage_rjcode_set or None

        # 2. 主查询带上链路上下文。命中即可识别返回里的简中翻译版。
        primary_result = await self.check_duplicate(
            rjcode, use_cache, extra_match_rjcodes=extra_for_lookup
        )
        results[rjcode] = primary_result

        try:
            if len(linked_works) > 1:
                logger.info(
                    f"[Kikoeru关联查询] 发现 {len(linked_works)} 个关联作品: {list(linked_works.keys())}"
                )

                # 3. 查询所有关联作品，每条同样带链路上下文。
                linked_rjcodes = [workno for workno in linked_works.keys() if workno != rjcode]

                if linked_rjcodes:
                    logger.info(
                        f"[Kikoeru关联查询] 将查询所有 {len(linked_rjcodes)} 个关联作品: {linked_rjcodes}"
                    )
                    linked_results = await self.check_duplicates_batch(
                        linked_rjcodes, use_cache, extra_match_rjcodes=extra_for_lookup
                    )
                    results.update(linked_results)

                    # 4. 记录找到的作品
                    found_works = [rj for rj, res in results.items() if res.is_found and rj != rjcode]
                    if found_works:
                        logger.info(
                            f"[Kikoeru关联查询] 在关联作品中找到 {len(found_works)} 个: {found_works}"
                        )
                else:
                    logger.info("[Kikoeru关联查询] 没有关联作品")
            else:
                logger.info(f"[Kikoeru关联查询] {rjcode} 没有关联作品")

            # 5. 兜底：链路全部未命中时，沿用同语言相关翻译的标题相似度补查。
            found_works = [res for res in results.values() if getattr(res, 'is_found', False)]
            if not found_works:
                related_translation_results = await self._find_related_translation_candidates(
                    rjcode, linked_works
                )
                if related_translation_results:
                    logger.info(
                        "[Kikoeru关联查询] 关联链未命中，补查到 %s 个同语言相关翻译作品: %s",
                        len(related_translation_results),
                        list(related_translation_results.keys()),
                    )
                    results.update(related_translation_results)

        except Exception as e:
            logger.warning("[Kikoeru关联查询] 关联查询过程异常 %s: %s", rjcode, e)

        return results

    async def search_circle_works(self, keyword: str, max_pages: int = 200) -> List[Dict]:
        """按 works 页面实际搜索链路分页拉取社团作品。
        改进：1) 社团名强过滤；2) 从第1页获取 total_pages 限制循环上限；
              3) 剩余页并发分批拉取（每批5页）；4) 连续3批无命中提前终止。
        """
        if not self.config.enabled:
            return []
        if not await self._ensure_valid_token():
            return []

        session = await self._get_session()
        headers = self._get_headers()
        normalized_keyword = str(keyword or "").strip()

        # 先访问 works 页面，保持和前端搜索页一致的会话/来源语义。
        try:
            async with session.get(
                self._build_keyword_works_page_url(normalized_keyword),
                headers=self._get_page_headers(normalized_keyword),
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            ) as response:
                await response.text()
        except Exception as exc:
            logger.warning("[Kikoeru] 社团 works 页面预热失败 keyword=%s: %s", normalized_keyword, exc)

        def _circle_matches(work: dict) -> bool:
            """判断作品的社团名是否与搜索关键词匹配（全文搜索会混入其他社团作品）。"""
            if not normalized_keyword:
                return True
            wc = work.get("circle") if isinstance(work.get("circle"), dict) else {}
            cn = str(wc.get("name", "") or "").strip()
            if not cn:
                return True  # 无社团名字段时保留，不误杀
            return cn == normalized_keyword or normalized_keyword in cn or cn in normalized_keyword

        def _extract_total_pages(data: dict) -> int:
            return self._extract_total_pages(data)

        async def _fetch_page(page: int) -> Optional[dict]:
            url = self._build_keyword_search_url(normalized_keyword, page=page)
            try:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except Exception as exc:
                logger.warning("[Kikoeru] 社团搜索失败 page=%s keyword=%s: %s", page, keyword, exc)
                return None

        def _collect_works(data: dict, seen_ids: set, out: list) -> int:
            filtered = {'works': [work for work in (data.get('works', []) if isinstance(data, dict) else []) if isinstance(work, dict) and _circle_matches(work)]}
            return self._collect_works_unique(filtered, seen_ids, out)

        all_works: List[Dict] = []
        seen_ids: Set[int] = set()

        # 第1页：顺序拉取，获得 total_pages 上限
        data1 = await _fetch_page(1)
        if not data1:
            return all_works
        _collect_works(data1, seen_ids, all_works)
        total_pages = _extract_total_pages(data1)
        if total_pages <= 0:
            total_pages = max_pages
        effective_max = min(total_pages, max(1, int(max_pages)))
        if effective_max <= 1:
            return all_works

        # 剩余页：每批 5 页并发拉取，连续 3 批无命中则提前终止
        BATCH = 5
        consecutive_empty_batches = 0
        for batch_start in range(2, effective_max + 1, BATCH):
            if consecutive_empty_batches >= 3:
                break
            pages = list(range(batch_start, min(batch_start + BATCH, effective_max + 1)))
            results = await asyncio.gather(*[_fetch_page(p) for p in pages], return_exceptions=True)
            batch_added = 0
            for res in results:
                if isinstance(res, Exception) or res is None:
                    continue
                batch_added += _collect_works(res, seen_ids, all_works)
            if batch_added > 0:
                consecutive_empty_batches = 0
            else:
                consecutive_empty_batches += 1

        logger.info("[Kikoeru] 社团搜索完成 keyword=%s works=%d effective_max_pages=%d",
                    keyword, len(all_works), effective_max)
        return all_works

    async def close(self):
        """关闭 HTTP Session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
        self._search_response_cache.clear()
        logger.info("Kikoeru 查重缓存已清除")


# 全局服务实例
_kikoeru_service: Optional[KikoeruDuplicateService] = None


def get_kikoeru_service() -> KikoeruDuplicateService:
    """获取 Kikoeru 查重服务实例（单例）"""
    global _kikoeru_service
    if _kikoeru_service is None:
        _kikoeru_service = KikoeruDuplicateService()
    return _kikoeru_service


async def check_kikoeru_duplicate(rjcode: str, use_cache: bool = True) -> KikoeruCheckResult:
    """
    快捷函数：检查作品是否在 Kikoeru 服务器中
    
    Args:
        rjcode: RJ号
        use_cache: 是否使用缓存
    
    Returns:
        KikoeruCheckResult: 查重结果
    """
    service = get_kikoeru_service()
    return await service.check_duplicate(rjcode, use_cache)
