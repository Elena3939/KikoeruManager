import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import requests
import logging
import json

from ..config.settings import get_config
from ..models.database import WorkMetadata as WorkMetadataModel, get_db
from ..core.task_engine import Task
from ..core.dlsite_service import get_dlsite_service

logger = logging.getLogger(__name__)

class WorkMetadata:
    """作品元数据。"""
    def __init__(self):
        self.rjcode: str = ""
        self.work_name: str = ""
        self.maker_id: str = ""
        self.maker_name: str = ""
        self.release_date: str = ""
        self.series_name: Optional[str] = None
        self.series_id: Optional[str] = None
        self.age_category: str = ""
        self.tags: list = []
        self.cvs: list = []
        self.cover_url: str = ""
    
    def to_dict(self) -> dict:
        return {
            'rjcode': self.rjcode,
            'work_name': self.work_name,
            'maker_id': self.maker_id,
            'maker_name': self.maker_name,
            'release_date': self.release_date,
            'series_name': self.series_name,
            'series_id': self.series_id,
            'age_category': self.age_category,
            'tags': self.tags,
            'cvs': self.cvs,
            'cover_url': self.cover_url
        }

class MetadataService:
    """元数据服务。"""

    def __init__(self):
        # 不缓存配置，保证每次都读取最新配置。
        self._session = None

    @property
    def config(self):
        """动态获取最新配置。"""
        return get_config()

    @property
    def session(self):
        """获取 requests Session，并同步当前代理配置。"""
        if self._session is None:
            self._session = requests.Session()

        # 每次访问时都刷新代理配置。
        if self.config.metadata.http_proxy:
            self._session.proxies = {
                'http': self.config.metadata.http_proxy,
                'https': self.config.metadata.http_proxy
            }
        else:
            self._session.proxies = {}

        return self._session
    
    async def fetch(self, path: str, task: Task) -> dict:
        """
        从路径中提取 RJ 号并获取元数据。
        """
        rjcode = self._extract_rjcode(path)
        if not rjcode and task is not None:
            task_metadata = getattr(task, "task_metadata", {}) or {}
            for candidate in (
                task_metadata.get("rjcode"),
                task_metadata.get("inferred_rjcode"),
                getattr(task, "rjcode", None),
            ):
                rjcode = self._extract_rjcode(str(candidate or ""), search_subfolders=False) or str(candidate or "").strip().upper()
                if rjcode:
                    logger.info("元数据服务使用任务上下文中的 RJ 号回退: %s", rjcode)
                    break
        if not rjcode:
            raise Exception(f"无法从路径中提取 RJ 号: {path}")

        task.update_progress(65, f"获取元数据 {rjcode}")

        if self.config.metadata.cache_enabled:
            cached = self._get_cached_metadata(rjcode)
            if cached:
                logger.info("使用缓存元数据: %s", rjcode)
                return cached.to_dict()

        metadata = None
        try:
            metadata = await self._fetch_from_dlsite_product_info(rjcode)
        except Exception as exc:
            logger.warning("[%s] DLsite product_info 链路失败: %s", rjcode, exc)

        if metadata is None:
            try:
                metadata = await self._fetch_from_dlsite(rjcode)
            except Exception as exc:
                logger.warning("[%s] DLsite API 直连链路失败: %s", rjcode, exc)

        if metadata is None:
            logger.warning("[%s] 所有元数据链路都失败，降级为最小元数据", rjcode)
            metadata = self._build_minimal_metadata(rjcode, path)

        if self.config.metadata.cache_enabled:
            self._cache_metadata(metadata)

        return metadata.to_dict()

    async def _resolve_original_maker_fields(self, product: Dict, rjcode: str) -> Dict[str, str]:
        translation_info = dict(product.get('translation_info') or {})
        original_workno = str(
            translation_info.get('original_workno')
            or translation_info.get('parent_workno')
            or ''
        ).strip().upper()
        is_original = translation_info.get('is_original', True)

        maker_fields = {
            'maker_id': product.get('maker_id', '') or '',
            'maker_name': product.get('maker_name', '') or '',
            'original_workno': original_workno,
        }
        if is_original or not original_workno:
            return maker_fields

        try:
            product_info = await get_dlsite_service().get_product_info(
                original_workno,
                locale='ja-JP',
            )
            original_product = dict((product_info or {}).get('product') or {})
            if original_product:
                maker_fields['maker_id'] = original_product.get('maker_id', '') or maker_fields['maker_id']
                maker_fields['maker_name'] = original_product.get('maker_name', '') or maker_fields['maker_name']
                logger.info(
                    "[%s] 使用原作社团信息: original=%s maker_name=%s",
                    rjcode,
                    original_workno,
                    maker_fields['maker_name'],
                )
        except Exception as exc:
            logger.warning("[%s] 获取原作社团信息失败 %s: %s", rjcode, original_workno, exc)

        return maker_fields
    
    def _extract_rjcode(self, path: str, search_subfolders: bool = True) -> Optional[str]:
        """从路径中提取 RJ 号。

        支持格式:
        - RJ123456, RJ12345678
        - VJ123456, BJ123456
        - 纯数字目录名: 1503161 -> RJ01503161
        - 带前缀的数字: 39.RJ01570159 -> RJ01570159
        - 支持从嵌套路径中提取 RJ 号
        - 直接提取失败时支持递归扫描子目录

        Args:
            path: 要提取的路径
            search_subfolders: 是否递归搜索子目录
        """
        pattern = r'[RVB]J(\d{8}|\d{6})(?!\d)'
        match = re.search(pattern, path, re.IGNORECASE)
        if match:
            return match.group(0).upper()

        path_parts = re.split(r'[\\/]', path)
        if path_parts:
            last_part = path_parts[-1]
            clean_name = re.sub(r'^\d+\.', '', last_part)
            num_match = re.match(r'^(\d{8}|\d{6})$', clean_name)
            if num_match:
                num = num_match.group(1)
                return f"RJ{num}"

        if search_subfolders and os.path.isdir(path):
            logger.debug("当前路径未直接提取到 RJ 号，尝试搜索子目录: %s", path)
            try:
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)

                    if os.path.isdir(item_path):
                        sub_rjcode = self._extract_rjcode(item_path, search_subfolders=True)
                        if sub_rjcode:
                            logger.debug(f"从子目录找到 RJ 号: {sub_rjcode} (路径: {item_path})")
                            return sub_rjcode
                    elif os.path.isfile(item_path):
                        file_rjcode = self._extract_rjcode(item_path, search_subfolders=False)
                        if file_rjcode:
                            logger.debug(f"从子文件找到 RJ 号: {file_rjcode} (路径: {item_path})")
                            return file_rjcode
            except Exception as e:
                logger.warning("搜索子目录失败: %s", e)

        return None
    
    def _get_cached_metadata(self, rjcode: str) -> Optional[WorkMetadataModel]:
        """从缓存获取元数据。"""
        db = next(get_db())
        try:
            cached = db.query(WorkMetadataModel).filter(
                WorkMetadataModel.rjcode == rjcode
            ).first()
            
            if cached is not None and cached.expires_at > datetime.now():
                return cached
            return None
        finally:
            db.close()
    
    def _cache_metadata(self, metadata: WorkMetadata):
        """把元数据缓存到数据库。"""
        db = next(get_db())
        try:
            db.query(WorkMetadataModel).filter(
                WorkMetadataModel.rjcode == metadata.rjcode
            ).delete()

            cached = WorkMetadataModel(
                rjcode=metadata.rjcode,
                work_name=metadata.work_name,
                maker_id=metadata.maker_id,
                maker_name=metadata.maker_name,
                release_date=metadata.release_date,
                series_name=metadata.series_name,
                series_id=metadata.series_id,
                age_category=metadata.age_category,
                tags=metadata.tags,
                cvs=metadata.cvs,
                cover_url=metadata.cover_url,
                expires_at=datetime.now() + timedelta(days=30)
            )
            db.add(cached)
            db.commit()
        except Exception as e:
            logger.error("缓存元数据失败: %s", e)
            db.rollback()
        finally:
            db.close()

    def _build_minimal_metadata(self, rjcode: str, path: str) -> WorkMetadata:
        """构建最小可用元数据，避免整条处理链中断。"""
        metadata = WorkMetadata()
        metadata.rjcode = rjcode

        path_name = os.path.basename(os.path.normpath(path or ''))
        display_name = re.sub(r'^[RVB]J(?:\d{8}|\d{6})(?!\d)[\s._-]*', '', path_name, flags=re.IGNORECASE)
        display_name = re.sub(r'^\d+\.', '', display_name).strip()

        metadata.work_name = display_name or rjcode
        metadata.age_category = 'ADL'
        return metadata

    async def _build_metadata_from_dlsite_product(self, rjcode: str, product: Dict) -> WorkMetadata:
        metadata = WorkMetadata()
        metadata.rjcode = product.get('workno', rjcode)
        metadata.work_name = product.get('work_name', '')
        maker_fields = await self._resolve_original_maker_fields(product, rjcode)
        metadata.maker_id = maker_fields.get('maker_id', '')
        metadata.maker_name = maker_fields.get('maker_name', '')
        metadata.release_date = product.get('regist_date', '')[:10]
        metadata.series_name = product.get('series_name')
        metadata.series_id = product.get('series_id')
        metadata.cover_url = 'https:' + product.get('image_main', {}).get('url', '')

        age_category = product.get('age_category', 3)
        if age_category == 1:
            metadata.age_category = 'GEN'
        elif age_category == 2:
            metadata.age_category = 'R15'
        else:
            metadata.age_category = 'ADL'

        for genre in product.get('genres', []):
            metadata.tags.append(genre.get('name', ''))

        creators = product.get('creaters', {})
        if isinstance(creators, dict) and 'voice_by' in creators:
            for cv in creators['voice_by']:
                metadata.cvs.append(cv.get('name', ''))

        translation_info = product.get('translation_info')
        if translation_info:
            logger.info(f"[{rjcode}] 检测到翻译信息: {translation_info}")

            locale_map = {
                'CHI_HANS': 'zh-CN',
                'CHI_HANT': 'zh-TW',
                'ENG': 'en-US',
                'KOR': 'ko-KR',
                'SPA': 'es-ES',
                'DEU': 'de-DE',
                'FRA': 'fr-FR',
                'IND': 'id-ID',
                'ITA': 'it-IT',
                'POR': 'pt-PT',
                'SWE': 'sv-SE',
                'THA': 'th-TH',
                'VIE': 'vi-VN'
            }

            translated_name = None

            if not translation_info.get('is_original', True):
                lang_code = translation_info.get('lang')
                if lang_code:
                    try:
                        logger.info(f"[{rjcode}] 处理翻译作品，原语言: {lang_code}")

                        tried_locales = []

                        if lang_code != 'CHI_HANS':
                            logger.info(f"[{rjcode}] 尝试获取简体中文标题")
                            translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                            tried_locales.append('zh-CN')
                            if translated_name:
                                logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")

                        if not translated_name and lang_code != 'CHI_HANT':
                            logger.info(f"[{rjcode}] 简体中文不可用，尝试获取繁体中文标题")
                            translated_name = await self._fetch_translated_title(rjcode, 'zh-TW', validate_chinese=True)
                            tried_locales.append('zh-TW')
                            if translated_name:
                                logger.info(f"[{rjcode}] 成功获取繁体中文翻译标题: {translated_name}")

                        if not translated_name:
                            dlsite_locale = locale_map.get(lang_code, lang_code)
                            logger.info(f"[{rjcode}] 已尝试 {tried_locales}，使用作品原 locale {dlsite_locale}")
                            should_validate = lang_code in ['CHI_HANS', 'CHI_HANT']
                            translated_name = await self._fetch_translated_title(rjcode, str(dlsite_locale), validate_chinese=should_validate)
                            if translated_name:
                                logger.info(f"[{rjcode}] 使用 {lang_code} 翻译标题: {translated_name}")
                    except Exception as e:
                        logger.warning(f"[{rjcode}] 获取翻译标题失败: {e}")

            elif translation_info.get('is_translation_agree', False):
                logger.info(f"[{rjcode}] 原作仅存在翻译申请信息，忽略，不视为实际翻译作品")

            if translated_name:
                metadata.work_name = translated_name

        return metadata

    async def _fetch_from_dlsite_product_info(self, rjcode: str) -> Optional[WorkMetadata]:
        await asyncio.sleep(self.config.metadata.sleep_interval)

        try:
            product_info = await get_dlsite_service().get_product_info(
                rjcode,
                locale=self.config.metadata.locale,
            )
            if not product_info or not product_info.get('product'):
                return None

            if product_info.get('fallback_used'):
                logger.info(
                    "[%s] DLsite fallback 命中: requested=%s parent=%s locale=%s",
                    rjcode,
                    product_info.get('requested_workno') or rjcode,
                    product_info.get('parent_workno') or '',
                    self.config.metadata.locale,
                )

            return await self._build_metadata_from_dlsite_product(
                rjcode,
                product_info.get('product') or {},
            )
        except Exception as e:
            logger.warning(f"[{rjcode}] DLsite product_info 链路失败，回退到直连 API: {e}")
            return None
    
    async def _fetch_from_dlsite(self, rjcode: str) -> WorkMetadata:
        """通过 DLsite API 直连获取元数据。"""
        await asyncio.sleep(self.config.metadata.sleep_interval)

        product = None
        try:
            dlsite_service = get_dlsite_service()
            product_info = await dlsite_service.get_product_info(
                rjcode,
                locale=self.config.metadata.locale,
            )
            if product_info and product_info.get('product'):
                product = product_info.get('product') or {}
                if product_info.get('fallback_used'):
                    logger.info(
                        "[%s] DLsite fallback 命中: requested=%s parent=%s locale=%s",
                        rjcode,
                        product_info.get('requested_workno') or rjcode,
                        product_info.get('parent_workno') or '',
                        self.config.metadata.locale,
                    )
        except Exception as e:
            logger.warning(f"[{rjcode}] DLsite fallback product_info 获取失败，继续直连 API: {e}")
        
        # 获取基础元数据，使用配置指定的 locale。
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={self.config.metadata.locale}"
        
        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()
            
            data = response.json()
            if not data or len(data) == 0:
                raise Exception(f"作品未找到: {rjcode}")
            
            product = data[0]
            metadata = WorkMetadata()
            metadata.rjcode = product.get('workno', rjcode)
            metadata.work_name = product.get('work_name', '')

            maker_fields = await self._resolve_original_maker_fields(product, rjcode)
            metadata.maker_id = maker_fields.get('maker_id', '')
            metadata.maker_name = maker_fields.get('maker_name', '')
            metadata.release_date = product.get('regist_date', '')[:10]
            metadata.series_name = product.get('series_name')
            metadata.series_id = product.get('series_id')
            metadata.cover_url = 'https:' + product.get('image_main', {}).get('url', '')
            
            # 年龄分级
            age_category = product.get('age_category', 3)
            if age_category == 1:
                metadata.age_category = 'GEN'
            elif age_category == 2:
                metadata.age_category = 'R15'
            else:
                metadata.age_category = 'ADL'
            
            # 标签
            for genre in product.get('genres', []):
                metadata.tags.append(genre.get('name', ''))
            
            # 声优
            creators = product.get('creaters', {})
            if isinstance(creators, dict) and 'voice_by' in creators:
                for cv in creators['voice_by']:
                    metadata.cvs.append(cv.get('name', ''))
            
            # 检查是否有可用的翻译标题。
            translation_info = product.get('translation_info')
            if translation_info:
                logger.info(f"[{rjcode}] 检测到翻译信息: {translation_info}")
                
                # 语言代码映射
                locale_map = {
                    'CHI_HANS': 'zh-CN',
                    'CHI_HANT': 'zh-TW',
                    'ENG': 'en-US',
                    'KOR': 'ko-KR',
                    'SPA': 'es-ES',
                    'DEU': 'de-DE',
                    'FRA': 'fr-FR',
                    'IND': 'id-ID',
                    'ITA': 'it-IT',
                    'POR': 'pt-PT',
                    'SWE': 'sv-SE',
                    'THA': 'th-TH',
                    'VIE': 'vi-VN'
                }
                
                translated_name = None
                
                # 情况 1: 翻译作品（子作品）
                if not translation_info.get('is_original', True):
                    lang_code = translation_info.get('lang')
                    if lang_code:
                        try:
                            logger.info(f"[{rjcode}] 处理翻译作品，原语言: {lang_code}")
                            
                            tried_locales = []
                            
                            if lang_code != 'CHI_HANS':
                                logger.info(f"[{rjcode}] 尝试获取简体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                                tried_locales.append('zh-CN')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                            
                            if not translated_name and lang_code != 'CHI_HANT':
                                logger.info(f"[{rjcode}] 简体中文不可用，尝试获取繁体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-TW', validate_chinese=True)
                                tried_locales.append('zh-TW')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取繁体中文翻译标题: {translated_name}")
                            
                            if not translated_name:
                                dlsite_locale = locale_map.get(lang_code, lang_code)
                                logger.info(f"[{rjcode}] 已尝试 {tried_locales}，使用作品原 locale {dlsite_locale}")
                                should_validate = lang_code in ['CHI_HANS', 'CHI_HANT']
                                translated_name = await self._fetch_translated_title(rjcode, str(dlsite_locale), validate_chinese=should_validate)
                                if translated_name:
                                    logger.info(f"[{rjcode}] 使用 {lang_code} 翻译标题: {translated_name}")
                        except Exception as e:
                            logger.warning(f"[{rjcode}] 获取翻译标题失败: {e}")
                
                # 情况 2: 原作仅存在翻译申请，不视为实际翻译作品
                elif translation_info.get('is_translation_agree', False):
                    logger.info(f"[{rjcode}] 原作仅存在翻译申请信息，忽略，不拉取伪翻译标题")
                
                if translated_name:
                    metadata.work_name = translated_name
            
            return metadata
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求 DLsite 失败: {e}")
            raise Exception(f"获取元数据失败: {e}")

    
    async def _fetch_translated_title(self, rjcode: str, lang: str, validate_chinese: bool = True) -> Optional[str]:
        """获取指定语言的翻译标题。"""
        await asyncio.sleep(self.config.metadata.sleep_interval)
        
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={lang}"
        logger.info(f"[{rjcode}] 调用翻译标题 API: {url}")
        
        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()
            
            data = response.json()
            if data and len(data) > 0:
                title = data[0].get('work_name')
                if title:
                    logger.info(f"[{rjcode}] API 返回标题: {title}")
                    if validate_chinese and self._contains_japanese_kana(title):
                        logger.warning(f"[{rjcode}] 标题包含日文假名，可能不是有效中文翻译: {title}")
                        return None
                    
                    return title
            
            return None
            
        except Exception as e:
            logger.error(f"[{rjcode}] 获取翻译标题失败: {e}")
            return None
    
    def _contains_japanese_kana(self, text: str) -> bool:
        """检查文本是否包含明显的日文假名。"""
        import re
        kana_pattern = r'[\u3040-\u309F\u30A0-\u30FF]'

        kana_count = len(re.findall(kana_pattern, text))
        total_chars = len(text.replace(' ', ''))

        if total_chars == 0:
            return False

        kana_ratio = kana_count / total_chars
        return kana_ratio > 0.05

    async def fetch_japanese_metadata(self, rjcode: str) -> Optional[dict]:
        """
        获取日文版本元数据。

        用于重命名模板中的非标题字段。对于翻译作品，会继续查询原作日文元数据。
        """
        await asyncio.sleep(self.config.metadata.sleep_interval)

        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale=ja-JP"
        logger.info(f"[{rjcode}] 获取日文元数据: {url}")

        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()

            data = response.json()
            if not data or len(data) == 0:
                logger.warning(f"[{rjcode}] 未找到日文元数据")
                return None

            product = data[0]

            translation_info = product.get('translation_info', {})
            original_workno = (
                translation_info.get('original_workno')
                or translation_info.get('parent_workno')
                or ''
            )
            is_original = translation_info.get('is_original', True)

            # 只要当前作品不是原作，就优先回溯到原作/父作品的日文元数据。
            # 某些翻译版链路不会稳定带 is_child，但 original_workno / parent_workno 仍然可用。
            if not is_original and original_workno:
                logger.info(f"[{rjcode}] 检测到翻译作品，原始作品: {original_workno}，继续获取原始作品的日文元数据")
                await asyncio.sleep(self.config.metadata.sleep_interval)

                original_url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_workno}&locale=ja-JP"
                logger.info(f"[{original_workno}] 获取原作日文元数据: {original_url}")

                try:
                    original_response = self.session.get(
                        original_url,
                        timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
                    )
                    original_response.raise_for_status()

                    original_data = original_response.json()
                    if original_data and len(original_data) > 0:
                        product = original_data[0]
                        logger.info(f"[{rjcode}] 使用原作 {original_workno} 的元数据: maker_name={product.get('maker_name')}")
                except Exception as e:
                    logger.warning(f"[{rjcode}] 获取原作 {original_workno} 元数据失败: {e}，继续使用当前作品数据")

            japanese_metadata = {
                'rjcode': product.get('workno', rjcode),
                'work_name': product.get('work_name', ''),
                'maker_id': product.get('maker_id', ''),
                'maker_name': product.get('maker_name', ''),
                'release_date': product.get('regist_date', '')[:10],
                'series_name': product.get('series_name'),
                'series_id': product.get('series_id'),
                'tags': [],
                'cvs': [],
            }

            # 标签
            for genre in product.get('genres', []):
                japanese_metadata['tags'].append(genre.get('name', ''))

            # 声优
            creators = product.get('creaters', {})
            if isinstance(creators, dict) and 'voice_by' in creators:
                for cv in creators['voice_by']:
                    japanese_metadata['cvs'].append(cv.get('name', ''))

            logger.info(f"[{rjcode}] 日文元数据获取成功: maker_name={japanese_metadata['maker_name']}, tags={len(japanese_metadata['tags'])}, cvs={len(japanese_metadata['cvs'])}")
            return japanese_metadata

        except Exception as e:
            logger.error(f"[{rjcode}] 获取日文元数据失败: {e}")
            return None
