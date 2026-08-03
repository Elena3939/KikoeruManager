import os
import re
import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Dict, List
import requests
import logging
import json

from ..config.settings import get_config
from ..models.database import WorkMetadata as WorkMetadataModel, get_db
from ..core.task_engine import Task
from ..core.dlsite_service import get_dlsite_service

logger = logging.getLogger(__name__)

_DLSITE_METADATA_CIRCUIT_FAILURE_THRESHOLD = 3
_DLSITE_METADATA_CIRCUIT_OPEN_SECONDS = 45.0
_DLSITE_METADATA_CIRCUIT: Dict[str, Any] = {
    "failures": 0,
    "open_until": 0.0,
    "last_error": "",
}


def _dlsite_metadata_circuit_state() -> Dict[str, Any]:
    now = time.monotonic()
    open_until = float(_DLSITE_METADATA_CIRCUIT.get("open_until") or 0.0)
    return {
        "open": open_until > now,
        "remaining_seconds": max(0.0, open_until - now),
        "failures": int(_DLSITE_METADATA_CIRCUIT.get("failures") or 0),
        "last_error": str(_DLSITE_METADATA_CIRCUIT.get("last_error") or ""),
    }


def get_dlsite_metadata_circuit_state() -> Dict[str, Any]:
    """返回 DLsite 元数据短熔断状态，供 API 慢日志补充上下文。"""
    return _dlsite_metadata_circuit_state()


def _record_dlsite_metadata_success() -> None:
    _DLSITE_METADATA_CIRCUIT["failures"] = 0
    _DLSITE_METADATA_CIRCUIT["open_until"] = 0.0
    _DLSITE_METADATA_CIRCUIT["last_error"] = ""


def _record_dlsite_metadata_failure(error: Any) -> None:
    failures = int(_DLSITE_METADATA_CIRCUIT.get("failures") or 0) + 1
    _DLSITE_METADATA_CIRCUIT["failures"] = failures
    _DLSITE_METADATA_CIRCUIT["last_error"] = str(error or "")[:240]
    if failures >= _DLSITE_METADATA_CIRCUIT_FAILURE_THRESHOLD:
        _DLSITE_METADATA_CIRCUIT["open_until"] = time.monotonic() + _DLSITE_METADATA_CIRCUIT_OPEN_SECONDS
        logger.warning(
            "[DLsite] 元数据短熔断开启 %.0fs failures=%s last_error=%s",
            _DLSITE_METADATA_CIRCUIT_OPEN_SECONDS,
            failures,
            _DLSITE_METADATA_CIRCUIT["last_error"],
        )


class WorkMetadata:
    """作品元数据。"""
    def __init__(self):
        self.rjcode: str = ""
        self.work_name: str = ""
        self.maker_id: str = ""
        self.maker_name: str = ""
        self.original_maker_name: str = ""
        self.translator_name: str = ""
        self.release_date: str = ""
        self.series_name: Optional[str] = None
        self.series_id: Optional[str] = None
        self.age_category: str = ""
        self.tags: list = []
        self.cvs: list = []
        self.cover_url: str = ""
        self.price_text: str = ""
        self.is_bonus_work: bool = False
        self.has_bonus: bool = False
        self.metadata_source: str = "unknown"
        self.metadata_verification_status: str = "unverified"
        self.metadata_verification_reason: str = ""
        self.metadata_evidence_source: str = ""
        self.resolved_workno: str = ""
        self.verified_parent_workno: str = ""
        self.verified_parent_child_relation: bool = False
        self.dlsite_circuit_open: bool = False
        self.rename_skipped_reason: str = ""
        # _apply_dlsite_bonus_info 成功时写入当前时间。
        # None 表示这次 metadata 没向 DLsite 实际确认过 bonus（落库后仍是 NULL，
        # build_circle_completion_view 会按 NULL 做一次性懒迁移）。
        self.bonus_info_checked_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            'rjcode': self.rjcode,
            'work_name': self.work_name,
            'maker_id': self.maker_id,
            'maker_name': self.maker_name,
            'original_maker_name': self.original_maker_name or self.maker_name,
            'translator_name': self.translator_name,
            'release_date': self.release_date,
            'series_name': self.series_name,
            'series_id': self.series_id,
            'age_category': self.age_category,
            'tags': self.tags,
            'cvs': self.cvs,
            'cover_url': self.cover_url,
            'price_text': self.price_text,
            'is_bonus_work': self.is_bonus_work,
            'has_bonus': self.has_bonus,
            'bonus_info_checked_at': self.bonus_info_checked_at.isoformat() if self.bonus_info_checked_at else None,
            'metadata_source': self.metadata_source,
            'metadata_verification_status': self.metadata_verification_status,
            'metadata_verification_reason': self.metadata_verification_reason,
            'metadata_evidence_source': self.metadata_evidence_source,
            'resolved_workno': self.resolved_workno,
            'verified_parent_workno': self.verified_parent_workno,
            'verified_parent_child_relation': self.verified_parent_child_relation,
            'dlsite_circuit_open': self.dlsite_circuit_open,
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

        self._session.headers.update(self._get_dlsite_headers())

        # 每次访问时都刷新代理配置。
        if self.config.metadata.http_proxy:
            proxy_url = self._normalize_proxy_url(self.config.metadata.http_proxy)
            self._session.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
        else:
            self._session.proxies = {}

        return self._session

    def _normalize_proxy_url(self, proxy: str) -> str:
        value = str(proxy or '').strip()
        if not value:
            return ''
        if re.match(r'^[a-z][a-z0-9+.-]*://', value, re.IGNORECASE):
            return value
        return f"http://{value}"

    def _product_info_timeout_seconds(self) -> float:
        override = os.environ.get("DLSITE_METADATA_PRODUCT_INFO_TIMEOUT", "").strip()
        if override:
            try:
                return max(1.0, float(override))
            except ValueError:
                logger.warning("DLSITE_METADATA_PRODUCT_INFO_TIMEOUT 无效，使用配置超时: %s", override)
        connect_timeout = float(getattr(self.config.metadata, "connect_timeout", 10) or 10)
        read_timeout = float(getattr(self.config.metadata, "read_timeout", 10) or 10)
        return max(5.0, connect_timeout + read_timeout + 2.0)

    async def _get_product_info_for_metadata(
        self,
        rjcode: str,
        *,
        locale: Optional[str] = None,
        purpose: str = "metadata",
        refresh: bool = False,
    ) -> Optional[Dict]:
        timeout = self._product_info_timeout_seconds()
        try:
            return await asyncio.wait_for(
                get_dlsite_service().get_product_info(
                    rjcode,
                    locale=locale,
                    refresh=refresh,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] DLsite product_info %s 超时 %.1fs，改走直连 product.json",
                rjcode,
                purpose,
                timeout,
            )
            return None

    def _get_dlsite_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.dlsite.com/maniax/',
            'Origin': 'https://www.dlsite.com',
            'DNT': '1',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-CH-UA': '"Chromium";v="120", "Google Chrome";v="120", "Not_A Brand";v="99"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Connection': 'keep-alive',
        }
    
    async def fetch(self, path: str, task: Task, force_refresh: bool = False) -> dict:
        """
        从路径中提取 RJ 号并获取元数据。
        """
        task_metadata = getattr(task, "task_metadata", {}) or {} if task is not None else {}
        # 密码库权威绑定：rjcode_lock 时优先使用任务上下文 RJ，避免被解压目录里的子作品 RJ 抢走。
        rjcode = None
        if task_metadata.get("rjcode_lock"):
            locked_raw = str(task_metadata.get("rjcode") or getattr(task, "rjcode", "") or "").strip()
            locked = self._extract_rjcode(locked_raw, search_subfolders=False) or locked_raw.upper()
            if locked and locked != "未知":
                rjcode = locked
                logger.info("元数据服务命中密码库权威 RJ 绑定: %s", rjcode)
        if not rjcode:
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

        if self.config.metadata.cache_enabled and not force_refresh:
            cached = self._get_cached_metadata(rjcode)
            if cached and not self._should_refresh_cached_metadata(cached):
                logger.info("使用缓存元数据: %s", rjcode)
                payload = cached.to_dict()
                payload["metadata_source"] = "cache"
                payload["dlsite_circuit_open"] = _dlsite_metadata_circuit_state()["open"]
                from .dlsite_metadata_trust import attach_dlsite_metadata_verification

                attach_dlsite_metadata_verification(payload, rjcode)
                return payload
            if cached:
                logger.info("缓存元数据命中但已判定需要刷新: %s maker_name=%s", rjcode, cached.maker_name)

        circuit_state = _dlsite_metadata_circuit_state()
        if circuit_state["open"] and not force_refresh:
            logger.warning(
                "[%s] DLsite 元数据短熔断中，跳过外部请求 remaining=%.1fs last_error=%s",
                rjcode,
                circuit_state["remaining_seconds"],
                circuit_state["last_error"],
            )
            metadata = self._build_minimal_metadata(rjcode, path)
            metadata.dlsite_circuit_open = True
            metadata.rename_skipped_reason = "DLsite 元数据短熔断中"
            payload = metadata.to_dict()
            from .dlsite_metadata_trust import attach_dlsite_metadata_verification

            attach_dlsite_metadata_verification(payload, rjcode)
            return payload

        metadata = None
        last_error = ""
        try:
            if force_refresh:
                metadata = await self._fetch_from_dlsite_product_info(
                    rjcode,
                    refresh=True,
                )
            else:
                metadata = await self._fetch_from_dlsite_product_info(rjcode)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("[%s] DLsite product_info 链路失败: %s", rjcode, exc)

        if metadata is None:
            try:
                metadata = await self._fetch_from_dlsite(rjcode)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("[%s] DLsite API 直连链路失败: %s", rjcode, exc)

        if metadata is None:
            logger.warning("[%s] 所有元数据链路都失败，降级为最小元数据", rjcode)
            _record_dlsite_metadata_failure(last_error or "metadata_not_found")
            metadata = self._build_minimal_metadata(rjcode, path)
        else:
            _record_dlsite_metadata_success()

        payload = metadata.to_dict()
        from .dlsite_metadata_trust import attach_dlsite_metadata_verification

        attach_dlsite_metadata_verification(payload, rjcode)
        metadata.metadata_verification_status = str(
            payload.get("metadata_verification_status") or "unverified"
        )
        metadata.metadata_verification_reason = str(
            payload.get("metadata_verification_reason") or ""
        )
        metadata.metadata_evidence_source = str(
            payload.get("metadata_evidence_source") or ""
        )
        if (
            self.config.metadata.cache_enabled
            and metadata.metadata_source != "minimal"
            and metadata.metadata_verification_status == "verified"
        ):
            self._cache_metadata(metadata)
        return payload

    def _should_refresh_cached_metadata(self, cached: WorkMetadataModel) -> bool:
        from .dlsite_metadata_trust import assess_dlsite_metadata

        verification = assess_dlsite_metadata(cached.to_dict(), cached.rjcode)
        if verification["status"] != "verified":
            return True

        maker_name = str(getattr(cached, "maker_name", "") or "").strip()
        work_name = str(getattr(cached, "work_name", "") or "").strip()
        release_date = str(getattr(cached, "release_date", "") or "").strip()
        tags = list(getattr(cached, "tags", None) or [])
        if not maker_name:
            return True

        normalized_maker = maker_name.lower()
        normalized_title = work_name.lower()
        suspicious_markers = (
            "みんなで翻訳",
            "everyone translation",
            "translation",
            "翻译",
            "翻訳",
        )
        if any(marker in normalized_maker for marker in suspicious_markers):
            return True

        # 某些翻译占位社团名会和作品标题几乎一样，命中时也强制刷新。
        if work_name and maker_name == work_name:
            return True

        # 旧版预告页缓存只抓到了标题/社团/封面，没有标签和发售日，需要强制重抓。
        if (
            ("予告作品" in work_name or "预告作品" in work_name or "announcement" in normalized_title)
            and not release_date
            and not tags
        ):
            return True

        return False

    async def _resolve_original_maker_fields(self, product: Dict, rjcode: str) -> Dict[str, str]:
        from .dlsite_metadata_trust import is_translation_placeholder_maker

        translation_info = dict(product.get('translation_info') or {})
        original_workno = str(
            translation_info.get('original_workno')
            or translation_info.get('parent_workno')
            or ''
        ).strip().upper()
        is_original = translation_info.get('is_original', True)
        page_maker_name = str(product.get('maker_name') or '').strip()
        translator_name = str(product.get('translator_name') or '').strip()
        if (
            not translator_name
            and not is_original
            and is_translation_placeholder_maker(page_maker_name)
        ):
            translator_name = page_maker_name

        maker_fields = {
            'maker_id': product.get('maker_id', '') or '',
            'maker_name': page_maker_name,
            'original_maker_name': str(
                product.get('original_maker_name') or page_maker_name
            ).strip(),
            'translator_name': translator_name,
            'original_workno': original_workno,
        }
        if is_translation_placeholder_maker(maker_fields["maker_name"]):
            maker_fields["maker_id"] = ""
            maker_fields["maker_name"] = ""
            maker_fields["original_maker_name"] = ""
        if is_original or not original_workno:
            return maker_fields

        try:
            product_info = await self._get_product_info_for_metadata(
                original_workno,
                locale='ja-JP',
                purpose="original_maker",
            )
            original_product = dict((product_info or {}).get('product') or {})
            verification_status = str(
                (product_info or {}).get("metadata_verification_status") or ""
            ).strip().lower()
            original_maker_name = str(
                original_product.get("maker_name") or ""
            ).strip()
            if (
                original_product
                and verification_status == "verified"
                and not is_translation_placeholder_maker(original_maker_name)
            ):
                maker_fields['maker_id'] = original_product.get('maker_id', '') or maker_fields['maker_id']
                maker_fields['maker_name'] = original_maker_name or maker_fields['maker_name']
                maker_fields['original_maker_name'] = original_maker_name or maker_fields['original_maker_name']
                logger.info(
                    "[%s] 使用原作社团信息: original=%s maker_name=%s",
                    rjcode,
                    original_workno,
                    maker_fields['maker_name'],
                )
            elif original_product:
                logger.warning(
                    "[%s] 原作社团元数据未通过验证，拒绝回填: original=%s status=%s maker=%s",
                    rjcode,
                    original_workno,
                    verification_status or "unverified",
                    original_maker_name or "missing",
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
            
            if cached is not None and cached.expires_at is not None and cached.expires_at > datetime.now():
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
                original_maker_name=metadata.original_maker_name or metadata.maker_name,
                translator_name=metadata.translator_name,
                release_date=metadata.release_date,
                series_name=metadata.series_name,
                series_id=metadata.series_id,
                age_category=metadata.age_category,
                tags=metadata.tags,
                cvs=metadata.cvs,
                cover_url=metadata.cover_url,
                price_text=metadata.price_text,
                is_bonus_work=bool(metadata.is_bonus_work),
                has_bonus=bool(metadata.has_bonus),
                metadata_verification_status=metadata.metadata_verification_status,
                metadata_verification_reason=metadata.metadata_verification_reason,
                metadata_evidence_source=metadata.metadata_evidence_source,
                resolved_workno=metadata.resolved_workno,
                verified_parent_workno=metadata.verified_parent_workno,
                verified_parent_child_relation=metadata.verified_parent_child_relation,
                # 仅在 _apply_dlsite_bonus_info 真的拉到 bonus 时才有值；
                # 否则保持 NULL，让浏览路径走一次懒迁移。
                bonus_info_checked_at=metadata.bonus_info_checked_at,
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
        metadata.metadata_source = "minimal"
        metadata.rjcode = rjcode

        path_name = os.path.basename(os.path.normpath(path or ''))
        display_name = re.sub(r'^[RVB]J(?:\d{8}|\d{6})(?!\d)[\s._-]*', '', path_name, flags=re.IGNORECASE)
        display_name = re.sub(r'^\d+\.', '', display_name).strip()

        metadata.work_name = display_name or rjcode
        metadata.age_category = 'ADL'
        return metadata

    def _normalize_cover_url(self, value: Any) -> str:
        url = str(value or '').strip()
        if not url:
            return ''
        if url.startswith('//'):
            return f'https:{url}'
        if url.startswith('https://') or url.startswith('http://'):
            return url
        return ''

    def _normalize_release_date(self, value: Any) -> str:
        return str(value or '')[:10]

    async def _apply_dlsite_bonus_info(self, metadata: WorkMetadata, rjcode: str) -> None:
        try:
            dlsite_service = get_dlsite_service()
            bonus_info = await dlsite_service.get_product_bonus_info(
                rjcode,
                locale=self.config.metadata.locale,
            )
            metadata.is_bonus_work = bool(bonus_info.get("is_bonus_work"))
            metadata.has_bonus = bool(bonus_info.get("has_bonus"))
            # 拉到结果后打上时间戳，标记此 metadata 已实际向 DLsite 确认过 bonus；
            # 失败抛异常时不会到这里，保留 None，让浏览路径有机会重试。
            metadata.bonus_info_checked_at = datetime.now()
        except Exception as exc:
            logger.debug("[%s] 获取 DLsite 特典字段失败: %s", rjcode, exc)

    async def lazy_refresh_bonus_for_cached_rjcodes(
        self,
        rjcodes: Iterable[str],
        *,
        max_concurrency: int = 6,
        force: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """针对存量旧条目（``work_metadata.bonus_info_checked_at IS NULL``）的一次性懒迁移。

        - 只补 ``is_bonus_work`` / ``has_bonus`` / ``bonus_info_checked_at`` 三个字段，
          不动其他元数据，避免拉慢浏览路径。
        - DLsite ``product_info_ajax`` 端点上有 24h cache + inflight 去重，单次社团
          浏览下命中率几乎 100%，不会真的发起 N 次跨网络请求。
        - 同一个 RJ 终身只触发一次（成功一次后写入 ``bonus_info_checked_at`` 即跳过）。
          若 DLsite 当下取不到（404 / 网络抖动），保留 NULL，下次浏览再试。
        - 返回 ``{rjcode: {"is_bonus_work", "has_bonus", "bonus_info_checked_at"}}``，
          调用方据此把更新合并到自己的 metadata_map / circle_works 行。

        ``force=True`` 时不看 ``bonus_info_checked_at`` 是否 NULL，对所有命中的 RJ
        强制重刷一次特典字段——给 ``refresh_circle_works`` 的"刷新选中作品"路径用，
        修复历史上因为 ``get_product_bonus_info`` 异常吞错（HTTP 失败也错误打了
        时间戳）导致 ``is_bonus_work=False`` 卡死的存量条目。这条路径直接走
        DLsite ``product_info_ajax``，靠它内部的 24h cache + inflight 去重防止
        雪崩，单社团一次性强刷的成本可控。
        """
        normalized: List[str] = []
        seen: set = set()
        for code in rjcodes or ():
            value = str(code or "").strip().upper()
            if not value:
                continue
            # 统一抽出 RJxxxx 形式，兼容上游传过来夹杂前缀 / 文件名片段的情况。
            match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", value)
            value = match.group(0) if match else value
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            return {}

        # 默认只挑真正需要补刷的：bonus_info_checked_at IS NULL。
        # 已有时间戳的就算 is_bonus_work=False 也"理论上"代表实际确认过不是特典，跳过。
        # ``force=True`` 时绕过这条过滤，对所有传进来的 RJ 都重新拉一次 product_info_ajax，
        # 用于修复"接口失败被错误打时间戳"的存量数据。
        db = next(get_db())
        try:
            query = db.query(WorkMetadataModel).filter(
                WorkMetadataModel.rjcode.in_(normalized)
            )
            if not force:
                query = query.filter(WorkMetadataModel.bonus_info_checked_at.is_(None))
            rows = query.all()
            pending = [str(row.rjcode or "").strip().upper() for row in rows if str(row.rjcode or "").strip()]
        finally:
            db.close()
        if not pending:
            return {}

        dlsite_service = get_dlsite_service()
        locale = self.config.metadata.locale
        sem = asyncio.Semaphore(max(1, int(max_concurrency or 1)))

        async def _resolve_one(rj: str) -> tuple[str, Optional[Dict[str, bool]]]:
            async with sem:
                try:
                    info = await dlsite_service.get_product_bonus_info(rj, locale=locale)
                    return rj, info or {}
                except Exception as exc:
                    logger.debug("[%s] 懒迁移 bonus 字段失败: %s", rj, exc)
                    return rj, None

        results = await asyncio.gather(*(_resolve_one(rj) for rj in pending))

        updated: Dict[str, Dict[str, Any]] = {}
        now = datetime.now()
        success_payload: Dict[str, tuple[bool, bool]] = {}
        for rj, info in results:
            if info is None:
                # 失败的不写 DB，保持 NULL，下次浏览再试。
                continue
            is_bonus = bool(info.get("is_bonus_work"))
            has_bonus_value = bool(info.get("has_bonus"))
            success_payload[rj] = (is_bonus, has_bonus_value)

        if success_payload:
            db = next(get_db())
            try:
                rows = (
                    db.query(WorkMetadataModel)
                    .filter(WorkMetadataModel.rjcode.in_(list(success_payload.keys())))
                    .all()
                )
                for row in rows:
                    rj = str(row.rjcode or "").strip().upper()
                    payload = success_payload.get(rj)
                    if not payload:
                        continue
                    is_bonus, has_bonus_value = payload
                    row.is_bonus_work = is_bonus
                    row.has_bonus = has_bonus_value
                    row.bonus_info_checked_at = now
                    updated[rj] = {
                        "is_bonus_work": is_bonus,
                        "has_bonus": has_bonus_value,
                        "bonus_info_checked_at": now.isoformat(),
                    }
                db.commit()
            except Exception as exc:
                logger.warning("更新 work_metadata bonus 字段失败: %s", exc)
                db.rollback()
                updated.clear()
            finally:
                db.close()

        if updated:
            logger.info("[bonus_lazy_refresh] 补刷 %s 个作品的 bonus 字段", len(updated))
        return updated

    async def _build_metadata_from_dlsite_product(self, rjcode: str, product: Dict) -> WorkMetadata:
        metadata = WorkMetadata()
        metadata.metadata_source = "dlsite"
        metadata.rjcode = product.get('workno', rjcode)
        metadata.resolved_workno = str(product.get('workno') or rjcode).strip().upper()
        metadata.verified_parent_workno = str(
            product.get('verified_parent_workno')
            or (product.get('translation_info') or {}).get('parent_workno')
            or ''
        ).strip().upper()
        metadata.verified_parent_child_relation = bool(
            product.get('verified_parent_child_relation')
        )
        metadata.work_name = product.get('work_name', '')
        maker_fields = await self._resolve_original_maker_fields(product, rjcode)
        metadata.maker_id = maker_fields.get('maker_id', '')
        metadata.maker_name = maker_fields.get('maker_name', '')
        metadata.original_maker_name = maker_fields.get('original_maker_name', '') or metadata.maker_name
        metadata.translator_name = maker_fields.get('translator_name', '')
        metadata.release_date = self._normalize_release_date(product.get('regist_date'))
        metadata.series_name = product.get('series_name')
        metadata.series_id = product.get('series_id')
        metadata.cover_url = self._normalize_cover_url((product.get('image_main') or {}).get('url'))
        dlsite_service = get_dlsite_service()
        if hasattr(dlsite_service, "_extract_product_price_text"):
            metadata.price_text = dlsite_service._extract_product_price_text(product)
        await self._apply_dlsite_bonus_info(metadata, rjcode)

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

    async def _fetch_from_dlsite_product_info(
        self,
        rjcode: str,
        *,
        refresh: bool = False,
    ) -> Optional[WorkMetadata]:
        await asyncio.sleep(self.config.metadata.sleep_interval)

        try:
            product_info = await self._get_product_info_for_metadata(
                rjcode,
                locale=self.config.metadata.locale,
                purpose="primary",
                refresh=refresh,
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

            metadata = await self._build_metadata_from_dlsite_product(
                rjcode,
                product_info.get('product') or {},
            )
            if product_info.get('fallback_used'):
                metadata.metadata_source = "fallback"
            metadata.metadata_evidence_source = str(
                product_info.get("fallback_source") or "dlsite_product"
            )
            metadata.metadata_verification_status = str(
                product_info.get("metadata_verification_status") or "unverified"
            )
            metadata.metadata_verification_reason = str(
                product_info.get("metadata_verification_reason") or ""
            )
            metadata.resolved_workno = str(
                product_info.get("resolved_workno")
                or metadata.resolved_workno
                or rjcode
            ).strip().upper()
            metadata.verified_parent_workno = str(
                product_info.get("parent_workno")
                or metadata.verified_parent_workno
                or ""
            ).strip().upper()
            metadata.verified_parent_child_relation = bool(
                metadata.verified_parent_child_relation
                or (
                    metadata.metadata_verification_status == "verified"
                    and metadata.verified_parent_workno
                    and metadata.metadata_evidence_source in {
                        "language_editions",
                        "page_embedded_original_match",
                        "translation_info",
                        "translation_page",
                    }
                )
            )
            return metadata
        except Exception as e:
            logger.warning(f"[{rjcode}] DLsite product_info 链路失败，回退到直连 API: {e}")
            return None
    
    async def _fetch_from_dlsite(self, rjcode: str) -> WorkMetadata:
        """通过 DLsite API 直连获取元数据。"""
        await asyncio.sleep(self.config.metadata.sleep_interval)
        
        # 获取基础元数据，使用配置指定的 locale。
        url = f"https://www.dlsite.com/maniax/api/=/product.json?workno={rjcode}&locale={self.config.metadata.locale}"
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout),
            )
            await asyncio.to_thread(response.raise_for_status)

            data = await asyncio.to_thread(response.json)
            if not data or len(data) == 0:
                raise Exception(f"作品未找到: {rjcode}")
            
            product = data[0]
            metadata = WorkMetadata()
            metadata.metadata_source = "dlsite"
            metadata.metadata_evidence_source = "dlsite_product"
            metadata.rjcode = product.get('workno', rjcode)
            metadata.work_name = product.get('work_name', '')

            maker_fields = await self._resolve_original_maker_fields(product, rjcode)
            metadata.maker_id = maker_fields.get('maker_id', '')
            metadata.maker_name = maker_fields.get('maker_name', '')
            metadata.original_maker_name = maker_fields.get('original_maker_name', '') or metadata.maker_name
            metadata.translator_name = maker_fields.get('translator_name', '')
            metadata.release_date = self._normalize_release_date(product.get('regist_date'))
            metadata.series_name = product.get('series_name')
            metadata.series_id = product.get('series_id')
            metadata.cover_url = self._normalize_cover_url((product.get('image_main') or {}).get('url'))
            dlsite_service = get_dlsite_service()
            if hasattr(dlsite_service, "_extract_product_price_text"):
                metadata.price_text = dlsite_service._extract_product_price_text(product)
            await self._apply_dlsite_bonus_info(metadata, rjcode)
            
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
            response = await asyncio.to_thread(
                self.session.get,
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout),
            )
            await asyncio.to_thread(response.raise_for_status)

            data = await asyncio.to_thread(response.json)
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
            response = await asyncio.to_thread(
                self.session.get,
                url,
                timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout),
            )
            await asyncio.to_thread(response.raise_for_status)

            data = await asyncio.to_thread(response.json)
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
                    original_response = await asyncio.to_thread(
                        self.session.get,
                        original_url,
                        timeout=(self.config.metadata.connect_timeout, self.config.metadata.read_timeout),
                    )
                    await asyncio.to_thread(original_response.raise_for_status)

                    original_data = await asyncio.to_thread(original_response.json)
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
                'release_date': self._normalize_release_date(product.get('regist_date')),
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
