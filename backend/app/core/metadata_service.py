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

logger = logging.getLogger(__name__)

class WorkMetadata:
    """作品元数据"""
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
    """元数据服务"""

    def __init__(self):
        # 不缓存配置，每次都获取最新配置
        # 因为 save_config 会创建新的 AppConfig 对象
        self._session = None

    @property
    def config(self):
        """动态获取最新配置"""
        return get_config()

    @property
    def session(self):
        """获取 requests Session，根据当前配置更新代理"""
        if self._session is None:
            self._session = requests.Session()

        # 每次访问时更新代理设置
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
        从路径中提取RJ号并获取元数据
        """
        # 从路径中提取RJ号
        rjcode = self._extract_rjcode(path)
        if not rjcode:
            raise Exception(f"无法从路径中提取RJ号: {path}")
        
        task.update_progress(65, f"获取元数据: {rjcode}")
        
        # 检查缓存
        if self.config.metadata.cache_enabled:
            cached = self._get_cached_metadata(rjcode)
            if cached:
                logger.info(f"使用缓存的元数据: {rjcode}")
                return cached.to_dict()
        
        # 从DLsite获取
        metadata = await self._fetch_from_dlsite(rjcode)
        
        # 缓存到数据库
        if self.config.metadata.cache_enabled:
            self._cache_metadata(metadata)
        
        return metadata.to_dict()
    
    def _extract_rjcode(self, path: str, search_subfolders: bool = True) -> Optional[str]:
        """从路径中提取 RJ 号
            
        支持格式：
        - RJ123456, RJ12345678
        - VJ123456, BJ123456
        - 纯数字目录名：01503161 -> RJ01503161
        - 带前缀的数字：39.RJ01570159 -> RJ01570159
        - 支持从嵌套路径中提取 RJ 号（会搜索整个路径字符串）
        - 支持递归搜索子目录（当直接提取失败时）
        
        Args:
            path: 要提取的路径
            search_subfolders: 是否递归搜索子目录（默认 True）
        """
        # 优先匹配标准格式 [RVB]J + 6/8 位数字（搜索整个路径）
        pattern = r'[RVB]J(\d{6}|\d{8})(?!\d)'
        match = re.search(pattern, path, re.IGNORECASE)
        if match:
            return match.group(0).upper()
            
        # 尝试从路径最后的目录/文件名中提取纯数字
        path_parts = re.split(r'[\\/]', path)
        if path_parts:
            last_part = path_parts[-1]
            # 移除常见前缀如 "39." 等
            clean_name = re.sub(r'^\d+\.', '', last_part)
            # 匹配 6 位或 8 位纯数字
            num_match = re.match(r'^(\d{6}|\d{8})$', clean_name)
            if num_match:
                num = num_match.group(1)
                return f"RJ{num}"
        
        # 如果直接提取失败，且允许搜索子目录
        if search_subfolders and os.path.isdir(path):
            logger.debug(f"从当前路径无法提取 RJ 号，尝试搜索子目录：{path}")
            try:
                # 遍历直接子目录
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    
                    # 优先检查文件夹（递归深入搜索）
                    if os.path.isdir(item_path):
                        # 尝试从子文件夹名提取（继续递归搜索子目录）
                        sub_rjcode = self._extract_rjcode(item_path, search_subfolders=True)
                        if sub_rjcode:
                            logger.debug(f"从子目录找到 RJ 号：{sub_rjcode} (路径：{item_path})")
                            return sub_rjcode
                    
                    # 其次检查文件（特别是压缩包）
                    elif os.path.isfile(item_path):
                        # 尝试从文件名提取
                        file_rjcode = self._extract_rjcode(item_path, search_subfolders=False)
                        if file_rjcode:
                            logger.debug(f"从子文件找到 RJ 号：{file_rjcode} (路径：{item_path})")
                            return file_rjcode
            except Exception as e:
                logger.warning(f"搜索子目录失败：{e}")
            
        return None
    
    def _get_cached_metadata(self, rjcode: str) -> Optional[WorkMetadataModel]:
        """从缓存获取元数据"""
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
        """缓存元数据到数据库"""
        db = next(get_db())
        try:
            # 删除旧缓存
            db.query(WorkMetadataModel).filter(
                WorkMetadataModel.rjcode == metadata.rjcode
            ).delete()
            
            # 创建新缓存
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
            logger.error(f"缓存元数据失败: {e}")
            db.rollback()
        finally:
            db.close()
    
    async def _fetch_from_dlsite(self, rjcode: str) -> WorkMetadata:
        """从DLsite API获取元数据（支持大家翻译）"""
        await asyncio.sleep(self.config.metadata.sleep_interval)
        
        # 获取基础数据（使用配置的语言）
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
            
            metadata.maker_id = product.get('maker_id', '')
            metadata.maker_name = product.get('maker_name', '')
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
            
            # 检查是否有大家翻译的中文标题
            translation_info = product.get('translation_info')
            if translation_info:
                logger.info(f"[{rjcode}] 发现翻译信息: {translation_info}")
                
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
                
                # 情况1: 翻译作品（子作品）
                if not translation_info.get('is_original', True):
                    lang_code = translation_info.get('lang')
                    if lang_code:
                        try:
                            logger.info(f"[{rjcode}] 处理翻译作品，原语言: {lang_code}")
                            
                            # 优先尝试简体中文，然后是繁体中文，最后是作品本身的语言
                            tried_locales = []
                            
                            # 策略1: 如果原语言不是简体中文，先尝试简体中文
                            if lang_code != 'CHI_HANS':
                                logger.info(f"[{rjcode}] 尝试获取简体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                                tried_locales.append('zh-CN')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                            
                            # 策略2: 如果简体中文失败且原语言不是繁体中文，尝试繁体中文
                            if not translated_name and lang_code != 'CHI_HANT':
                                logger.info(f"[{rjcode}] 简体中文不可用，尝试获取繁体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-TW', validate_chinese=True)
                                tried_locales.append('zh-TW')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取繁体中文翻译标题: {translated_name}")
                            
                            # 策略3: 使用作品本身的翻译语言
                            if not translated_name:
                                dlsite_locale = locale_map.get(lang_code, lang_code)
                                logger.info(f"[{rjcode}] 已尝试{tried_locales}，使用作品原locale {dlsite_locale}")
                                should_validate = lang_code in ['CHI_HANS', 'CHI_HANT']
                                translated_name = await self._fetch_translated_title(rjcode, str(dlsite_locale), validate_chinese=should_validate)
                                if translated_name:
                                    logger.info(f"[{rjcode}] 使用{lang_code}翻译标题: {translated_name}")
                        except Exception as e:
                            logger.warning(f"[{rjcode}] 获取翻译标题失败: {e}")
                
                # 情况2: 原作但有"大家来翻译"申请
                elif translation_info.get('is_translation_agree', False):
                    logger.info(f"[{rjcode}] 原作但有翻译申请，检查是否有可用的中文翻译")
                    
                    translation_status = translation_info.get('translation_status_for_translator', {})
                    logger.info(f"[{rjcode}] 翻译状态: {translation_status}")
                    
                    # 检查简体中文是否可用
                    chi_hans_status = translation_status.get('CHI_HANS', {})
                    if chi_hans_status.get('is_available', False) and not chi_hans_status.get('is_denied', True):
                        logger.info(f"[{rjcode}] 简体中文翻译申请可用，尝试获取")
                        try:
                            translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                            if translated_name:
                                logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                        except Exception as e:
                            logger.warning(f"[{rjcode}] 获取简体中文翻译标题失败: {e}")
                    
                    # 如果简体中文不可用或获取失败，尝试繁体中文
                    if not translated_name:
                        chi_hant_status = translation_status.get('CHI_HANT', {})
                        if chi_hant_status.get('is_available', False) and not chi_hant_status.get('is_denied', True):
                            logger.info(f"[{rjcode}] 繁体中文翻译申请可用，尝试获取")
                            try:
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-TW', validate_chinese=True)
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取繁体中文翻译标题: {translated_name}")
                            except Exception as e:
                                logger.warning(f"[{rjcode}] 获取繁体中文翻译标题失败: {e}")
                
                if translated_name:
                    metadata.work_name = translated_name
            
            return metadata
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求DLsite失败: {e}")
            raise Exception(f"获取元数据失败: {e}")
    
    async def _fetch_translated_title(self, rjcode: str, lang: str, validate_chinese: bool = True) -> Optional[str]:
        """获取指定语言的翻译标题
        
        Args:
            rjcode: RJ号
            lang: 语言代码 (如 'zh-CN', 'zh-TW')
            validate_chinese: 是否验证标题不包含日文假名（中文翻译标题通常不包含假名）
        """
        await asyncio.sleep(self.config.metadata.sleep_interval)
        
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={lang}"
        logger.info(f"[{rjcode}] 调用翻译标题API: {url}")
        
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
                    logger.info(f"[{rjcode}] API返回标题: {title}")
                    
                    # 验证是否包含日文假名（如果需要）
                    # 中文翻译标题通常不包含日文假名，如果包含说明可能是日文原文
                    if validate_chinese and self._contains_japanese_kana(title):
                        logger.warning(f"[{rjcode}] 标题包含日文假名，可能是日文原文而非翻译: {title}")
                        return None
                    
                    return title
            
            return None
            
        except Exception as e:
            logger.error(f"[{rjcode}] 获取翻译标题失败: {e}")
            return None
    
    def _contains_japanese_kana(self, text: str) -> bool:
        """检查文本是否包含日文假名（平假名或片假名）

        日文标题通常包含假名，而中文翻译标题通常不包含
        返回True表示可能是日文标题，False表示可能是中文标题
        """
        import re
        # 平假名范围: \u3040-\u309F
        # 片假名范围: \u30A0-\u30FF
        # 日文标点符号: \u3000-\u303F (包含全角标点)
        kana_pattern = r'[\u3040-\u309F\u30A0-\u30FF]'

        kana_count = len(re.findall(kana_pattern, text))
        total_chars = len(text.replace(' ', ''))  # 排除空格

        if total_chars == 0:
            return False

        # 如果假名占比超过5%，认为是日文标题
        kana_ratio = kana_count / total_chars
        return kana_ratio > 0.05

    async def fetch_japanese_metadata(self, rjcode: str) -> Optional[dict]:
        """
        获取日语版本的元数据
        用于重命名模板中非标题字段的日语原文

        对于翻译作品，会获取原始作品的元数据以获取真正的社团名称

        Args:
            rjcode: RJ号

        Returns:
            日语元数据字典，包含 maker_name, cvs, tags 等字段
        """
        await asyncio.sleep(self.config.metadata.sleep_interval)

        # 首先获取当前作品的信息，检查是否是翻译作品
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale=ja-JP"
        logger.info(f"[{rjcode}] 获取日语元数据: {url}")

        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()

            data = response.json()
            if not data or len(data) == 0:
                logger.warning(f"[{rjcode}] 日语元数据未找到")
                return None

            product = data[0]

            # 检查是否是翻译作品，如果是则获取原始作品的元数据
            translation_info = product.get('translation_info', {})
            original_workno = translation_info.get('original_workno')

            # 如果是翻译作品（子作品），获取原始作品的元数据以获取真正的社团名称
            if translation_info.get('is_child') and original_workno:
                logger.info(f"[{rjcode}] 检测到翻译作品，原始作品: {original_workno}，获取原始作品的日语元数据")
                await asyncio.sleep(self.config.metadata.sleep_interval)

                original_url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_workno}&locale=ja-JP"
                logger.info(f"[{original_workno}] 获取原始作品日语元数据: {original_url}")

                try:
                    original_response = self.session.get(
                        original_url,
                        timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
                    )
                    original_response.raise_for_status()

                    original_data = original_response.json()
                    if original_data and len(original_data) > 0:
                        # 使用原始作品的元数据
                        product = original_data[0]
                        logger.info(f"[{rjcode}] 使用原始作品 {original_workno} 的元数据: maker_name={product.get('maker_name')}")
                except Exception as e:
                    logger.warning(f"[{rjcode}] 获取原始作品 {original_workno} 元数据失败: {e}，使用当前作品元数据")

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

            logger.info(f"[{rjcode}] 日语元数据获取成功: maker_name={japanese_metadata['maker_name']}, tags={len(japanese_metadata['tags'])}, cvs={len(japanese_metadata['cvs'])}")
            return japanese_metadata

        except Exception as e:
            logger.error(f"[{rjcode}] 获取日语元数据失败: {e}")
            return None
