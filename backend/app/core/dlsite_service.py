"""
DLsite API 服务 - 用于获取作品关联信息和翻译链
参考 VoiceLinks 的实现
"""
import asyncio
import httpx
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class TranslationInfo:
    """翻译信息"""
    is_original: bool = False
    is_parent: bool = False
    is_child: bool = False
    parent_workno: Optional[str] = None
    original_workno: Optional[str] = None
    lang: str = "JPN"


@dataclass
class LinkedWork:
    """关联作品信息"""
    workno: str
    work_type: str  # original, translation, child_translation
    lang: str = "JPN"
    title: str = ""
    
    def to_dict(self) -> dict:
        return {
            'workno': self.workno,
            'work_type': self.work_type,
            'lang': self.lang,
            'title': self.title
        }


class DLsiteApiService:
    """DLsite API 服务"""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.cache: Dict[str, Dict] = {}  # 缓存 API 响应
        self.cache_ttl = timedelta(hours=24)  # 缓存 24 小时
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self.client is None or self.client.is_closed:
            # 从配置加载代理设置
            from ..config.settings import get_config
            config = get_config()
            proxy_url = None
            if config.metadata.http_proxy:
                proxy_url = f"http://{config.metadata.http_proxy}"
                logger.debug(f"[DLsite] 使用代理：{proxy_url}")
            
            self.client = httpx.AsyncClient(
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                },
                timeout=httpx.Timeout(30.0, connect=10.0),
                verify=False,  # 禁用 SSL 验证（避免某些网络环境问题）
                follow_redirects=True,
                proxy=proxy_url  # 使用配置的代理
            )
        return self.client
    
    async def _fetch_api(self, url: str) -> Optional[Dict]:
        """从 DLsite API 获取数据"""
        cache_key = url
        
        # 检查缓存
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug(f"使用缓存数据：{url}")
                return cached_data['data']
        
        logger.info(f"[DLsite] 正在请求 API: {url}")
        
        try:
            client = await self._get_client()
            logger.debug(f"[DLsite] 使用客户端配置：verify=False, timeout=30s")
            response = await client.get(url)
            
            logger.info(f"[DLsite] 响应状态码：{response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                # 保存到缓存
                self.cache[cache_key] = {
                    'data': data,
                    'timestamp': datetime.now()
                }
                return data
            elif response.status_code == 404:
                logger.warning(f"API 返回 404: {url}")
                return None
            else:
                logger.error(f"API 请求失败：{url}, 状态码：{response.status_code}")
                return None
        except httpx.ConnectError as e:
            logger.error(f"API 连接失败：{url}")
            logger.error(f"错误详情：{str(e)}")
            logger.error("可能原因：1) 网络连接问题 2) DLsite 服务器不可达 3) 防火墙阻止")
            return None
        except httpx.ReadTimeout as e:
            logger.error(f"API 读取超时：{url} (超过 30 秒)")
            logger.error(f"错误详情：{str(e)}")
            return None
        except Exception as e:
            logger.error(f"API 请求异常：{url}")
            logger.error(f"错误类型：{type(e).__name__}")
            logger.error(f"错误详情：{str(e)}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    async def get_translation_info(self, rjcode: str) -> TranslationInfo:
        """
        获取作品的翻译信息
        
        返回:
            TranslationInfo: 包含 is_original, is_parent, is_child 等信息
        """
        # 尝试从 API2 获取
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}"
        data = await self._fetch_api(url)
        
        if data and isinstance(data, list) and len(data) > 0:
            product = data[0]
            translation_info = product.get('translation_info', {})
            
            return TranslationInfo(
                is_original=translation_info.get('is_original', False),
                is_parent=translation_info.get('is_parent', False),
                is_child=translation_info.get('is_child', False),
                parent_workno=translation_info.get('parent_workno'),
                original_workno=translation_info.get('original_workno'),
                lang=translation_info.get('lang', 'JPN')
            )
        
        return TranslationInfo(is_original=True)
    
    async def get_linked_works(self, rjcode: str) -> Dict[str, LinkedWork]:
        """
        获取作品的关联作品（包括原版和所有翻译版本）
        
        关联作品包括：
        - 原版作品（日文）
        - 所有翻译版本（简中、繁中、英文等不同译者，RJ 号各不相同）
        - 子翻译版本（嵌套翻译）
        
        返回:
            Dict[str, LinkedWork]: RJ 号到作品信息的映射
        """
        trans = await self.get_translation_info(rjcode)
        result = {}
        
        try:
            # 如果是翻译版本，先获取原版作品的关联信息
            original_rjcode = rjcode
            if not trans.is_original and trans.original_workno:
                original_rjcode = trans.original_workno
                logger.info(f"[DLsite] {rjcode} 是翻译版本，从原版 {original_rjcode} 获取完整关联链")
            
            # 获取原版作品信息
            url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_rjcode}"
            data = await self._fetch_api(url)
            
            if not (data and isinstance(data, list) and len(data) > 0):
                logger.warning(f"[DLsite] API 返回空数据：{rjcode}")
                return {rjcode: LinkedWork(workno=rjcode, work_type='original', lang='JPN')}
            
            product = data[0]
            
            # 添加原版作品
            result[original_rjcode] = LinkedWork(workno=original_rjcode, work_type='original', lang='JPN')
            
            # 获取所有语言版本（翻译版本）- 包括不同译者的版本
            language_editions = product.get('language_editions', [])
            if isinstance(language_editions, dict):
                language_editions = list(language_editions.values())
            
            for edition in language_editions:
                workno = edition.get('workno')
                lang = edition.get('lang', 'JPN')
                title = edition.get('work_name', '')
                if workno and workno not in result:
                    result[workno] = LinkedWork(
                        workno=workno,
                        work_type='translation',
                        lang=lang,
                        title=title
                    )
                    logger.debug(f"[DLsite] 添加翻译版本：{workno} ({lang})")
            
            # 额外检查：如果当前作品有子作品（嵌套翻译），也添加进来
            child_worknos = product.get('child_worknos', [])
            if isinstance(child_worknos, list):
                for child_workno in child_worknos:
                    if child_workno not in result:
                        result[child_workno] = LinkedWork(
                            workno=child_workno,
                            work_type='child_translation',
                            lang=trans.lang
                        )
                        logger.debug(f"[DLsite] 添加子翻译版本：{child_workno}")
            
            # 如果当前查询的是翻译版本，确保它也在结果中
            if rjcode not in result:
                result[rjcode] = LinkedWork(
                    workno=rjcode,
                    work_type='translation' if not trans.is_original else 'original',
                    lang=trans.lang
                )
            
            logger.info(f"[DLsite] {rjcode} 关联作品 ({len(result)}个): {list(result.keys())}")
            return result
            
        except Exception as e:
            logger.error(f"获取关联作品失败 {rjcode}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {rjcode: LinkedWork(workno=rjcode, work_type='original', lang='JPN')}
    
    async def get_full_linkage(self, rjcode: str, cue_languages: List[str] = None) -> Dict[str, LinkedWork]:
        """
        获取作品的完整关联链（包括所有语言版本）
        
        Args:
            rjcode: RJ 号
            cue_languages: 需要查询的语言列表，如 ['CHI_HANS', 'CHI_HANT', 'ENG']
        
        返回:
            Dict[str, LinkedWork]: 所有关联作品的映射
        """
        if cue_languages is None:
            cue_languages = ['CHI_HANS', 'CHI_HANT']
        
        # 首先获取翻译信息
        trans = await self.get_translation_info(rjcode)
        
        # 如果是非原作品，先从原作品开始查询
        original_rjcode = rjcode
        if not trans.is_original and trans.original_workno:
            original_rjcode = trans.original_workno
        
        # 检查缓存
        cache_key = f"{original_rjcode}_{'_'.join(sorted(cue_languages))}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_ttl:
                logger.debug(f"使用完整关联链缓存：{original_rjcode}")
                return cached_data['data']
        
        # 获取原作品的关联信息
        result = await self.get_linked_works(original_rjcode)
        
        try:
            url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={original_rjcode}"
            data = await self._fetch_api(url)
            
            if data and isinstance(data, list) and len(data) > 0:
                product = data[0]
                language_editions = product.get('language_editions', [])
                if isinstance(language_editions, dict):
                    language_editions = list(language_editions.values())
                
                # 对每种语言版本递归查询
                for edition in language_editions:
                    lang = edition.get('lang', 'JPN')
                    if lang not in cue_languages:
                        continue
                    
                    workno = edition.get('workno')
                    if workno and workno not in result:
                        # 递归获取该语言版本的关联作品
                        linked = await self.get_linked_works(workno)
                        for k, v in linked.items():
                            if k not in result:
                                result[k] = v
                
                # 保存到缓存
                self.cache[cache_key] = {
                    'data': result,
                    'timestamp': datetime.now()
                }
        
        except Exception as e:
            logger.error(f"获取完整关联链失败 {rjcode}: {e}")
        
        return result
    
    async def get_work_info(self, rjcode: str) -> Optional[Dict]:
        """获取作品详细信息"""
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}"
        data = await self._fetch_api(url)
        
        if data and isinstance(data, list) and len(data) > 0:
            product = data[0]
            return {
                'rjcode': rjcode,
                'title': product.get('work_name', ''),
                'maker_name': product.get('maker_name', ''),
                'release_date': product.get('regist_date', ''),
                'file_size': product.get('contents_file_size', 0),
                'cover_url': product.get('image_main', {}).get('url', '')
            }
        return None
    
    def get_rj_chain(self, rjcode: str, trans: TranslationInfo) -> List[str]:
        """获取 RJ 号关联链"""
        chain = [rjcode]
        if trans.is_child:
            if trans.parent_workno:
                chain.append(trans.parent_workno)
            if trans.original_workno:
                chain.append(trans.original_workno)
        elif trans.is_parent:
            if trans.original_workno:
                chain.append(trans.original_workno)
        return chain
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self.client:
            await self.client.aclose()


# 全局服务实例
_dlsite_service: Optional[DLsiteApiService] = None


def get_dlsite_service() -> DLsiteApiService:
    """获取 DLsite API 服务实例（单例）"""
    global _dlsite_service
    if _dlsite_service is None:
        _dlsite_service = DLsiteApiService()
    return _dlsite_service
