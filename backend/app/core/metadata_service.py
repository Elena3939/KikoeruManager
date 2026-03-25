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
    """浣滃搧鍏冩暟鎹?"""
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
    """鍏冩暟鎹湇鍔?"""

    def __init__(self):
        # 涓嶇紦瀛橀厤缃紝姣忔閮借幏鍙栨渶鏂伴厤缃?
        # 鍥犱负 save_config 浼氬垱寤烘柊鐨?AppConfig 瀵硅薄
        self._session = None

    @property
    def config(self):
        """鍔ㄦ€佽幏鍙栨渶鏂伴厤缃?"""
        return get_config()

    @property
    def session(self):
        """鑾峰彇 requests Session锛屾牴鎹綋鍓嶉厤缃洿鏂颁唬鐞?"""
        if self._session is None:
            self._session = requests.Session()

        # 姣忔璁块棶鏃舵洿鏂颁唬鐞嗚缃?
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
        浠庤矾寰勪腑鎻愬彇RJ鍙峰苟鑾峰彇鍏冩暟鎹?
        """
        # 浠庤矾寰勪腑鎻愬彇RJ鍙?
        rjcode = self._extract_rjcode(path)
        if not rjcode:
            raise Exception(f"鏃犳硶浠庤矾寰勪腑鎻愬彇RJ鍙? {path}")
        
        task.update_progress(65, f"鑾峰彇鍏冩暟鎹? {rjcode}")
        
        # 妫€鏌ョ紦瀛?
        if self.config.metadata.cache_enabled:
            cached = self._get_cached_metadata(rjcode)
            if cached:
                logger.info(f"浣跨敤缂撳瓨鐨勫厓鏁版嵁: {rjcode}")
                return cached.to_dict()
        
        # 浠嶥Lsite鑾峰彇
        metadata = await self._fetch_from_dlsite_product_info(rjcode)
        if metadata is None:
            metadata = await self._fetch_from_dlsite(rjcode)
        
        # 缂撳瓨鍒版暟鎹簱
        if self.config.metadata.cache_enabled:
            self._cache_metadata(metadata)
        
        return metadata.to_dict()
    
    def _extract_rjcode(self, path: str, search_subfolders: bool = True) -> Optional[str]:
        """浠庤矾寰勪腑鎻愬彇 RJ 鍙?
            
        鏀寔鏍煎紡锛?
        - RJ123456, RJ12345678
        - VJ123456, BJ123456
        - 绾暟瀛楃洰褰曞悕锛?1503161 -> RJ01503161
        - 甯﹀墠缂€鐨勬暟瀛楋細39.RJ01570159 -> RJ01570159
        - 鏀寔浠庡祵濂楄矾寰勪腑鎻愬彇 RJ 鍙凤紙浼氭悳绱㈡暣涓矾寰勫瓧绗︿覆锛?
        - 鏀寔閫掑綊鎼滅储瀛愮洰褰曪紙褰撶洿鎺ユ彁鍙栧け璐ユ椂锛?
        
        Args:
            path: 瑕佹彁鍙栫殑璺緞
            search_subfolders: 鏄惁閫掑綊鎼滅储瀛愮洰褰曪紙榛樿 True锛?
        """
        # 浼樺厛鍖归厤鏍囧噯鏍煎紡 [RVB]J + 6/8 浣嶆暟瀛楋紙鎼滅储鏁翠釜璺緞锛?
        pattern = r'[RVB]J(\d{6}|\d{8})(?!\d)'
        match = re.search(pattern, path, re.IGNORECASE)
        if match:
            return match.group(0).upper()
            
        # 灏濊瘯浠庤矾寰勬渶鍚庣殑鐩綍/鏂囦欢鍚嶄腑鎻愬彇绾暟瀛?
        path_parts = re.split(r'[\\/]', path)
        if path_parts:
            last_part = path_parts[-1]
            # 绉婚櫎甯歌鍓嶇紑濡?"39." 绛?
            clean_name = re.sub(r'^\d+\.', '', last_part)
            # 鍖归厤 6 浣嶆垨 8 浣嶇函鏁板瓧
            num_match = re.match(r'^(\d{6}|\d{8})$', clean_name)
            if num_match:
                num = num_match.group(1)
                return f"RJ{num}"
        
        # 濡傛灉鐩存帴鎻愬彇澶辫触锛屼笖鍏佽鎼滅储瀛愮洰褰?
        if search_subfolders and os.path.isdir(path):
            logger.debug(f"浠庡綋鍓嶈矾寰勬棤娉曟彁鍙?RJ 鍙凤紝灏濊瘯鎼滅储瀛愮洰褰曪細{path}")
            try:
                # 閬嶅巻鐩存帴瀛愮洰褰?
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    
                    # 浼樺厛妫€鏌ユ枃浠跺す锛堥€掑綊娣卞叆鎼滅储锛?
                    if os.path.isdir(item_path):
                        # 灏濊瘯浠庡瓙鏂囦欢澶瑰悕鎻愬彇锛堢户缁€掑綊鎼滅储瀛愮洰褰曪級
                        sub_rjcode = self._extract_rjcode(item_path, search_subfolders=True)
                        if sub_rjcode:
                            logger.debug(f"从子目录找到 RJ 号: {sub_rjcode} (路径: {item_path})")
                            return sub_rjcode
                    
                    # 鍏舵妫€鏌ユ枃浠讹紙鐗瑰埆鏄帇缂╁寘锛?
                    elif os.path.isfile(item_path):
                        # 灏濊瘯浠庢枃浠跺悕鎻愬彇
                        file_rjcode = self._extract_rjcode(item_path, search_subfolders=False)
                        if file_rjcode:
                            logger.debug(f"从子文件找到 RJ 号: {file_rjcode} (路径: {item_path})")
                            return file_rjcode
            except Exception as e:
                logger.warning(f"鎼滅储瀛愮洰褰曞け璐ワ細{e}")
            
        return None
    
    def _get_cached_metadata(self, rjcode: str) -> Optional[WorkMetadataModel]:
        """浠庣紦瀛樿幏鍙栧厓鏁版嵁"""
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
        """缂撳瓨鍏冩暟鎹埌鏁版嵁搴?"""
        db = next(get_db())
        try:
            # 鍒犻櫎鏃х紦瀛?
            db.query(WorkMetadataModel).filter(
                WorkMetadataModel.rjcode == metadata.rjcode
            ).delete()
            
            # 鍒涘缓鏂扮紦瀛?
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
            logger.error(f"缂撳瓨鍏冩暟鎹け璐? {e}")
            db.rollback()
        finally:
            db.close()

    async def _build_metadata_from_dlsite_product(self, rjcode: str, product: Dict) -> WorkMetadata:
        metadata = WorkMetadata()
        metadata.rjcode = product.get('workno', rjcode)
        metadata.work_name = product.get('work_name', '')

        metadata.maker_id = product.get('maker_id', '')
        metadata.maker_name = product.get('maker_name', '')
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
            logger.info(f"[{rjcode}] 閸欐垹骞囩紙鏄忕槯娣団剝浼? {translation_info}")

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
                logger.info(f"[{rjcode}] 原作存在翻译申请，检查是否有可用中文翻译")

                translation_status = translation_info.get('translation_status_for_translator', {})
                logger.info(f"[{rjcode}] 翻译状态: {translation_status}")

                chi_hans_status = translation_status.get('CHI_HANS', {})
                if chi_hans_status.get('is_available', False) and not chi_hans_status.get('is_denied', True):
                    logger.info(f"[{rjcode}] 简体中文翻译申请可用，尝试获取")
                    try:
                        translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                        if translated_name:
                            logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                    except Exception as e:
                        logger.warning(f"[{rjcode}] 获取简体中文翻译标题失败: {e}")

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
                    "[%s] DLsite 缈昏瘧鐗?fallback 鍛戒腑: requested=%s parent=%s locale=%s",
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
            logger.warning(f"[{rjcode}] DLsite product_info 閾捐矾澶辫触锛屽洖閫€鐩磋繛 API: {e}")
            return None
    
    async def _fetch_from_dlsite(self, rjcode: str) -> WorkMetadata:
        """浠嶥Lsite API鑾峰彇鍏冩暟鎹紙鏀寔澶у缈昏瘧锛?"""
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
                        "[%s] DLsite 缈昏瘧鐗?fallback 鍛戒腑: requested=%s parent=%s locale=%s",
                        rjcode,
                        product_info.get('requested_workno') or rjcode,
                        product_info.get('parent_workno') or '',
                        self.config.metadata.locale,
                    )
        except Exception as e:
            logger.warning(f"[{rjcode}] DLsite fallback product_info 鑾峰彇澶辫触锛屽洖閫€鐩磋繛 API: {e}")
        
        # 鑾峰彇鍩虹鏁版嵁锛堜娇鐢ㄩ厤缃殑璇█锛?
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={self.config.metadata.locale}"
        
        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()
            
            data = response.json()
            if not data or len(data) == 0:
                raise Exception(f"浣滃搧鏈壘鍒? {rjcode}")
            
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
            
            # 骞撮緞鍒嗙骇
            age_category = product.get('age_category', 3)
            if age_category == 1:
                metadata.age_category = 'GEN'
            elif age_category == 2:
                metadata.age_category = 'R15'
            else:
                metadata.age_category = 'ADL'
            
            # 鏍囩
            for genre in product.get('genres', []):
                metadata.tags.append(genre.get('name', ''))
            
            # 澹颁紭
            creators = product.get('creaters', {})
            if isinstance(creators, dict) and 'voice_by' in creators:
                for cv in creators['voice_by']:
                    metadata.cvs.append(cv.get('name', ''))
            
            # 妫€鏌ユ槸鍚︽湁澶у缈昏瘧鐨勪腑鏂囨爣棰?
            translation_info = product.get('translation_info')
            if translation_info:
                logger.info(f"[{rjcode}] 鍙戠幇缈昏瘧淇℃伅: {translation_info}")
                
                # 璇█浠ｇ爜鏄犲皠
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
                
                # 鎯呭喌1: 缈昏瘧浣滃搧锛堝瓙浣滃搧锛?
                if not translation_info.get('is_original', True):
                    lang_code = translation_info.get('lang')
                    if lang_code:
                        try:
                            logger.info(f"[{rjcode}] 处理翻译作品，原语言: {lang_code}")
                            
                            # 浼樺厛灏濊瘯绠€浣撲腑鏂囷紝鐒跺悗鏄箒浣撲腑鏂囷紝鏈€鍚庢槸浣滃搧鏈韩鐨勮瑷€
                            tried_locales = []
                            
                            # 绛栫暐1: 濡傛灉鍘熻瑷€涓嶆槸绠€浣撲腑鏂囷紝鍏堝皾璇曠畝浣撲腑鏂?
                            if lang_code != 'CHI_HANS':
                                logger.info(f"[{rjcode}] 尝试获取简体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                                tried_locales.append('zh-CN')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                            
                            # 绛栫暐2: 濡傛灉绠€浣撲腑鏂囧け璐ヤ笖鍘熻瑷€涓嶆槸绻佷綋涓枃锛屽皾璇曠箒浣撲腑鏂?
                            if not translated_name and lang_code != 'CHI_HANT':
                                logger.info(f"[{rjcode}] 简体中文不可用，尝试获取繁体中文标题")
                                translated_name = await self._fetch_translated_title(rjcode, 'zh-TW', validate_chinese=True)
                                tried_locales.append('zh-TW')
                                if translated_name:
                                    logger.info(f"[{rjcode}] 成功获取繁体中文翻译标题: {translated_name}")
                            
                            # 绛栫暐3: 浣跨敤浣滃搧鏈韩鐨勭炕璇戣瑷€
                            if not translated_name:
                                dlsite_locale = locale_map.get(lang_code, lang_code)
                                logger.info(f"[{rjcode}] 已尝试 {tried_locales}，使用作品原 locale {dlsite_locale}")
                                should_validate = lang_code in ['CHI_HANS', 'CHI_HANT']
                                translated_name = await self._fetch_translated_title(rjcode, str(dlsite_locale), validate_chinese=should_validate)
                                if translated_name:
                                    logger.info(f"[{rjcode}] 使用 {lang_code} 翻译标题: {translated_name}")
                        except Exception as e:
                            logger.warning(f"[{rjcode}] 获取翻译标题失败: {e}")
                
                # 鎯呭喌2: 鍘熶綔浣嗘湁"澶у鏉ョ炕璇?鐢宠
                elif translation_info.get('is_translation_agree', False):
                    logger.info(f"[{rjcode}] 原作存在翻译申请，检查是否有可用中文翻译")
                    
                    translation_status = translation_info.get('translation_status_for_translator', {})
                    logger.info(f"[{rjcode}] 翻译状态: {translation_status}")
                    
                    # 妫€鏌ョ畝浣撲腑鏂囨槸鍚﹀彲鐢?
                    chi_hans_status = translation_status.get('CHI_HANS', {})
                    if chi_hans_status.get('is_available', False) and not chi_hans_status.get('is_denied', True):
                        logger.info(f"[{rjcode}] 简体中文翻译申请可用，尝试获取")
                        try:
                            translated_name = await self._fetch_translated_title(rjcode, 'zh-CN', validate_chinese=True)
                            if translated_name:
                                logger.info(f"[{rjcode}] 成功获取简体中文翻译标题: {translated_name}")
                        except Exception as e:
                            logger.warning(f"[{rjcode}] 获取简体中文翻译标题失败: {e}")
                    
                    # 濡傛灉绠€浣撲腑鏂囦笉鍙敤鎴栬幏鍙栧け璐ワ紝灏濊瘯绻佷綋涓枃
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
            logger.error(f"璇锋眰DLsite澶辫触: {e}")
            raise Exception(f"鑾峰彇鍏冩暟鎹け璐? {e}")
    
    async def _fetch_translated_title(self, rjcode: str, lang: str, validate_chinese: bool = True) -> Optional[str]:
        """鑾峰彇鎸囧畾璇█鐨勭炕璇戞爣棰?
        
        Args:
            rjcode: RJ鍙?
            lang: 璇█浠ｇ爜 (濡?'zh-CN', 'zh-TW')
            validate_chinese: 鏄惁楠岃瘉鏍囬涓嶅寘鍚棩鏂囧亣鍚嶏紙涓枃缈昏瘧鏍囬閫氬父涓嶅寘鍚亣鍚嶏級
        """
        await asyncio.sleep(self.config.metadata.sleep_interval)
        
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={lang}"
        logger.info(f"[{rjcode}] 璋冪敤缈昏瘧鏍囬API: {url}")
        
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
                    logger.info(f"[{rjcode}] API杩斿洖鏍囬: {title}")
                    
                    # 楠岃瘉鏄惁鍖呭惈鏃ユ枃鍋囧悕锛堝鏋滈渶瑕侊級
                    # 涓枃缈昏瘧鏍囬閫氬父涓嶅寘鍚棩鏂囧亣鍚嶏紝濡傛灉鍖呭惈璇存槑鍙兘鏄棩鏂囧師鏂?
                    if validate_chinese and self._contains_japanese_kana(title):
                        logger.warning(f"[{rjcode}] 鏍囬鍖呭惈鏃ユ枃鍋囧悕锛屽彲鑳芥槸鏃ユ枃鍘熸枃鑰岄潪缈昏瘧: {title}")
                        return None
                    
                    return title
            
            return None
            
        except Exception as e:
            logger.error(f"[{rjcode}] 鑾峰彇缈昏瘧鏍囬澶辫触: {e}")
            return None
    
    def _contains_japanese_kana(self, text: str) -> bool:
        """妫€鏌ユ枃鏈槸鍚﹀寘鍚棩鏂囧亣鍚嶏紙骞冲亣鍚嶆垨鐗囧亣鍚嶏級

        鏃ユ枃鏍囬閫氬父鍖呭惈鍋囧悕锛岃€屼腑鏂囩炕璇戞爣棰橀€氬父涓嶅寘鍚?
        杩斿洖True琛ㄧず鍙兘鏄棩鏂囨爣棰橈紝False琛ㄧず鍙兘鏄腑鏂囨爣棰?
        """
        import re
        # 骞冲亣鍚嶈寖鍥? \u3040-\u309F
        # 鐗囧亣鍚嶈寖鍥? \u30A0-\u30FF
        # 鏃ユ枃鏍囩偣绗﹀彿: \u3000-\u303F (鍖呭惈鍏ㄨ鏍囩偣)
        kana_pattern = r'[\u3040-\u309F\u30A0-\u30FF]'

        kana_count = len(re.findall(kana_pattern, text))
        total_chars = len(text.replace(' ', ''))  # 鎺掗櫎绌烘牸

        if total_chars == 0:
            return False

        # 濡傛灉鍋囧悕鍗犳瘮瓒呰繃5%锛岃涓烘槸鏃ユ枃鏍囬
        kana_ratio = kana_count / total_chars
        return kana_ratio > 0.05

    async def fetch_japanese_metadata(self, rjcode: str) -> Optional[dict]:
        """
        鑾峰彇鏃ヨ鐗堟湰鐨勫厓鏁版嵁
        鐢ㄤ簬閲嶅懡鍚嶆ā鏉夸腑闈炴爣棰樺瓧娈电殑鏃ヨ鍘熸枃

        瀵逛簬缈昏瘧浣滃搧锛屼細鑾峰彇鍘熷浣滃搧鐨勫厓鏁版嵁浠ヨ幏鍙栫湡姝ｇ殑绀惧洟鍚嶇О

        Args:
            rjcode: RJ鍙?

        Returns:
            鏃ヨ鍏冩暟鎹瓧鍏革紝鍖呭惈 maker_name, cvs, tags 绛夊瓧娈?
        """
        await asyncio.sleep(self.config.metadata.sleep_interval)

        # 棣栧厛鑾峰彇褰撳墠浣滃搧鐨勪俊鎭紝妫€鏌ユ槸鍚︽槸缈昏瘧浣滃搧
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale=ja-JP"
        logger.info(f"[{rjcode}] 鑾峰彇鏃ヨ鍏冩暟鎹? {url}")

        try:
            response = self.session.get(
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
            )
            response.raise_for_status()

            data = response.json()
            if not data or len(data) == 0:
                logger.warning(f"[{rjcode}] 鏃ヨ鍏冩暟鎹湭鎵惧埌")
                return None

            product = data[0]

            # 妫€鏌ユ槸鍚︽槸缈昏瘧浣滃搧锛屽鏋滄槸鍒欒幏鍙栧師濮嬩綔鍝佺殑鍏冩暟鎹?
            translation_info = product.get('translation_info', {})
            original_workno = translation_info.get('original_workno')

            # 濡傛灉鏄炕璇戜綔鍝侊紙瀛愪綔鍝侊級锛岃幏鍙栧師濮嬩綔鍝佺殑鍏冩暟鎹互鑾峰彇鐪熸鐨勭ぞ鍥㈠悕绉?
            if translation_info.get('is_child') and original_workno:
                logger.info(f"[{rjcode}] 检测到翻译作品，原始作品: {original_workno}，继续获取原始作品的日文元数据")
                await asyncio.sleep(self.config.metadata.sleep_interval)

                original_url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_workno}&locale=ja-JP"
                logger.info(f"[{original_workno}] 鑾峰彇鍘熷浣滃搧鏃ヨ鍏冩暟鎹? {original_url}")

                try:
                    original_response = self.session.get(
                        original_url,
                        timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout)
                    )
                    original_response.raise_for_status()

                    original_data = original_response.json()
                    if original_data and len(original_data) > 0:
                        # 浣跨敤鍘熷浣滃搧鐨勫厓鏁版嵁
                        product = original_data[0]
                        logger.info(f"[{rjcode}] 浣跨敤鍘熷浣滃搧 {original_workno} 鐨勫厓鏁版嵁: maker_name={product.get('maker_name')}")
                except Exception as e:
                    logger.warning(f"[{rjcode}] 鑾峰彇鍘熷浣滃搧 {original_workno} 鍏冩暟鎹け璐? {e}锛屼娇鐢ㄥ綋鍓嶄綔鍝佸厓鏁版嵁")

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

            # 鏍囩
            for genre in product.get('genres', []):
                japanese_metadata['tags'].append(genre.get('name', ''))

            # 澹颁紭
            creators = product.get('creaters', {})
            if isinstance(creators, dict) and 'voice_by' in creators:
                for cv in creators['voice_by']:
                    japanese_metadata['cvs'].append(cv.get('name', ''))

            logger.info(f"[{rjcode}] 鏃ヨ鍏冩暟鎹幏鍙栨垚鍔? maker_name={japanese_metadata['maker_name']}, tags={len(japanese_metadata['tags'])}, cvs={len(japanese_metadata['cvs'])}")
            return japanese_metadata

        except Exception as e:
            logger.error(f"[{rjcode}] 鑾峰彇鏃ヨ鍏冩暟鎹け璐? {e}")
            return None
