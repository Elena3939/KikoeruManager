from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, BigInteger, Index, text, Float, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from datetime import datetime, timezone
import os
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

import orjson

# 自定义 JSON 序列化/反序列化钩子：
# SQLAlchemy 默认的 JSON 列类型会在物化 ORM 对象时对每行调用 stdlib json.loads，
# 对 activity_logs 这种 detail 较大的表 (~148μs/row) 在 5000 行窗口下能吃掉 ~700ms。
# orjson 实测比 stdlib json 快 3~5×，换上去后 list / children 接口的 JSON 反序列化
# 开销直接降到可忽略水平。
def _scrub_surrogates_for_json(value: Any) -> Any:
    """递归把 lone surrogate 代码点（U+D800–U+DFFF）转义成 \\udcXX 字面量。

    Linux 上 surrogateescape 文件名（7zz / unar 解压非 UTF-8 ZIP 时常见）会把
    无法解码的字节用 U+DC80–U+DCFF 代替留在 Python str 里。orjson 严格拒绝写入
    lone surrogate（``TypeError: surrogates not allowed``），导致 activity_logs /
    conflict_works 等 JSON 列整批 INSERT 失败。
    这里只在踩到时做一次性兜底转义，让数据可以落库；前端 ``decodeEscapedSurrogateName``
    会把 ``\\udc83`` 这种字面量按用户选择的编码再解回去。
    """
    if isinstance(value, str):
        if any('\ud800' <= ch <= '\udfff' for ch in value):
            return value.encode('utf-8', 'backslashreplace').decode('utf-8')
        return value
    if isinstance(value, dict):
        return {
            (_scrub_surrogates_for_json(k) if isinstance(k, str) else k): _scrub_surrogates_for_json(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_surrogates_for_json(v) for v in value]
    if isinstance(value, set):
        return [_scrub_surrogates_for_json(v) for v in value]
    return value


def _orjson_dumps(obj) -> str:
    # SA json_serializer 约定返回 str；orjson 返回 bytes，这里再 decode 一次
    try:
        return orjson.dumps(obj, default=str).decode('utf-8')
    except TypeError as exc:
        # 仅在 lone surrogate 这条具体路径上降级；其他 TypeError（不可序列化对象等）
        # 仍按原样抛出，避免吞掉真正的 bug。降级后保留对正常 UTF-8 路径的 3~5× 性能收益。
        if 'surrogates not allowed' not in str(exc):
            raise
        return orjson.dumps(_scrub_surrogates_for_json(obj), default=str).decode('utf-8')


def _orjson_loads(value):
    # PostgreSQL JSONB 读出来通常已经是 dict/list；迁移脚本和部分测试也可能给 str/bytes。
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    return orjson.loads(value)

def get_local_now():
    """获取当前本地时间（用于数据库默认值）"""
    return datetime.now()

Base = declarative_base()
JSON = JSONB

_NATURAL_SORT_NUMBER_RE = re.compile(r"(\d+)")
_NATURAL_SORT_DELIMITER = "\u0001"


def library_index_name_sort_key(value: Any) -> str:
    """生成可被 PostgreSQL btree 直接排序的文件名自然排序键。"""
    raw = str(value or "").casefold()
    parts: list[str] = []
    for part in _NATURAL_SORT_NUMBER_RE.split(raw):
        if not part:
            continue
        if part.isdigit():
            normalized = part.lstrip("0") or "0"
            parts.append(
                f"1{len(normalized):010d}{normalized}{len(part):010d}{_NATURAL_SORT_DELIMITER}"
            )
        else:
            escaped = (
                part
                .replace("\\", "\\\\")
                .replace(_NATURAL_SORT_DELIMITER, "\\u0001")
            )
            parts.append(f"0{escaped}{_NATURAL_SORT_DELIMITER}")
    return "".join(parts)

class Task(Base):
    """任务表"""
    __tablename__ = 'tasks'
    
    id = Column(String(36), primary_key=True)
    type = Column(String(20))  # EXTRACT, FILTER, METADATA, RENAME, AUTO_PROCESS
    status = Column(String(20))  # PENDING, PROCESSING, PAUSED, COMPLETED, FAILED
    source_path = Column(Text)
    output_path = Column(Text)
    progress = Column(Integer, default=0)
    current_step = Column(String(100))
    error_message = Column(Text)
    created_at = Column(DateTime, default=get_local_now)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    task_metadata = Column(JSON)  # renamed from metadata to avoid SQLAlchemy reserved word


class TaskCenterItem(Base):
    """任务中心事件期物化快照。

    当前阶段只做旁路写入和对照校验，任务中心 API 仍走旧聚合链路。
    """
    __tablename__ = 'task_center_items'

    item_id = Column(String(80), primary_key=True)
    engine_task_id = Column(String(36))
    domain = Column(String(40))
    status = Column(String(24))
    kind = Column(String(60))
    title = Column(Text)
    source_page = Column(String(80))
    source_action = Column(String(120))
    business_key = Column(Text)
    searchable_text = Column(Text)
    payload_json = Column(JSON)
    version = Column(Integer, default=0)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)


class TaskPhaseMetric(Base):
    """任务阶段耗时指标。

    这是旁路观测表：只记录任务某个阶段的耗时/吞吐，不参与任务状态流转。
    """
    __tablename__ = 'task_phase_metrics'

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), index=True)
    task_type = Column(String(60), index=True)
    phase = Column(String(80), index=True)
    resource = Column(String(40), index=True)
    status = Column(String(24), index=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    bytes_total = Column(BigInteger, nullable=False, default=0)
    items_total = Column(Integer, nullable=False, default=0)
    detail_json = Column(JSON)
    started_at = Column(DateTime, index=True)
    ended_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=get_local_now, index=True)

    __table_args__ = (
        Index('idx_task_phase_metrics_task_phase', 'task_id', 'phase'),
        Index('idx_task_phase_metrics_type_phase', 'task_type', 'phase'),
        Index('idx_task_phase_metrics_created_at', 'created_at'),
    )
    
class WorkMetadata(Base):
    """作品元数据表"""
    __tablename__ = 'work_metadata'
    
    rjcode = Column(String(20), primary_key=True)
    work_name = Column(Text)
    maker_id = Column(String(20))
    maker_name = Column(Text)
    release_date = Column(String(20))
    series_name = Column(Text)
    series_id = Column(String(20))
    age_category = Column(String(10))
    tags = Column(JSON)  # 列表
    cvs = Column(JSON)   # 列表
    cover_url = Column(Text)
    price_text = Column(String(80))
    is_bonus_work = Column(Boolean, default=False, index=True)
    has_bonus = Column(Boolean, default=False, index=True)
    # 标记 bonus 字段是否已经向 DLsite 实际确认过。
    # NULL = 老 schema 留下来的存量，从未实际计算过 bonus；
    # 写入时间 = 已经走过 _apply_dlsite_bonus_info / lazy refresh，is_bonus_work / has_bonus 是真值。
    # build_circle_completion_view 用这个字段做存量懒迁移，避免老条目永远卡在 False。
    bonus_info_checked_at = Column(DateTime, nullable=True)
    cached_at = Column(DateTime, default=get_local_now)
    expires_at = Column(DateTime)
    
    def to_dict(self):
        """转换为字典"""
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
            'cover_url': self.cover_url,
            'price_text': self.price_text or '',
            'is_bonus_work': bool(self.is_bonus_work),
            'has_bonus': bool(self.has_bonus),
            'bonus_info_checked_at': self.bonus_info_checked_at.isoformat() if self.bonus_info_checked_at else None,
            'cached_at': self.cached_at.isoformat() if self.cached_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }

class LibrarySnapshot(Base):
    """库存快照表"""
    __tablename__ = 'library_snapshot'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rjcode = Column(String(20), unique=True, index=True)
    folder_path = Column(Text)
    folder_size = Column(BigInteger)
    file_count = Column(Integer)
    scanned_at = Column(DateTime, default=get_local_now)
    
    __table_args__ = (
        Index('idx_rjcode', 'rjcode'),
    )

class ExistingFolderCache(Base):
    """已有文件夹扫描缓存表"""
    __tablename__ = 'existing_folder_cache'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_path = Column(Text, unique=True, index=True)  # 文件夹完整路径
    folder_name = Column(String(255))  # 文件夹名称
    rjcode = Column(String(20), index=True)  # RJ号
    
    # 查重信息（JSON格式存储）
    duplicate_info = Column(JSON, default=None)  # 查重结果
    conflict_count = Column(Integer, default=0)  # 冲突数量
    
    # 元数据
    file_count = Column(Integer, default=0)  # 文件数量
    folder_size = Column(BigInteger, default=0)  # 文件夹大小
    
    # 缓存时间
    cached_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    
    # 是否需要刷新
    needs_refresh = Column(Boolean, default=False)
    
    __table_args__ = (
        Index('idx_existing_folder_path', 'folder_path'),
        Index('idx_existing_rjcode', 'rjcode'),
        Index('idx_existing_cached_at', 'cached_at'),
    )

class ConflictWork(Base):
    """问题作品表"""
    __tablename__ = 'conflict_works'
    
    id = Column(String(36), primary_key=True)
    task_id = Column(String(36))
    rjcode = Column(String(20))
    conflict_type = Column(String(30))  # DUPLICATE, LANGUAGE_VARIANT, MULTIPLE_VERSIONS, LINKED_WORK
    existing_path = Column(Text)
    new_path = Column(Text)
    new_metadata = Column(JSON)
    status = Column(String(20), default='PENDING')  # PENDING, KEEP_NEW, KEEP_OLD, MERGE, SKIP, KEEP_BOTH
    created_at = Column(DateTime, default=get_local_now)
    
    # 关联作品信息（新增）
    linked_works_info = Column(JSON, default=list)  # 发现的关联作品列表
    analysis_info = Column(JSON, default=dict)  # 详细分析报告
    related_rjcodes = Column(JSON, default=list)  # 所有关联的 RJ 号

class WorkLinkage(Base):
    """作品关联表 - 存储作品关联链"""
    __tablename__ = 'work_linkages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    original_rjcode = Column(String(20), index=True)  # 原作品 RJ 号
    linked_rjcode = Column(String(20), index=True)   # 关联作品 RJ 号
    work_type = Column(String(20))  # original, parent, child
    lang = Column(String(20))       # 语言代码
    cached_at = Column(DateTime, default=get_local_now)
    expires_at = Column(DateTime)   # 缓存过期时间
    
    __table_args__ = (
        Index('idx_original_linked', 'original_rjcode', 'linked_rjcode'),
    )


class CircleCatalog(Base):
    """社团索引表"""
    __tablename__ = 'circle_catalogs'

    circle_id = Column(String(120), primary_key=True)
    circle_name = Column(Text)
    circle_name_normalized = Column(String(255), index=True)
    source_mask = Column(String(120), default='')
    last_indexed_at = Column(DateTime, default=get_local_now, index=True)
    last_local_sync_at = Column(DateTime)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    def to_dict(self):
        return {
            'circle_id': self.circle_id,
            'circle_name': self.circle_name,
            'circle_name_normalized': self.circle_name_normalized,
            'source_mask': self.source_mask or '',
            'last_indexed_at': self.last_indexed_at.isoformat() if self.last_indexed_at else None,
            'last_local_sync_at': self.last_local_sync_at.isoformat() if self.last_local_sync_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CircleExternalIdentity(Base):
    """社团外部身份映射缓存（DLsite/Kikoeru）"""
    __tablename__ = 'circle_external_identities'

    id = Column(Integer, primary_key=True, autoincrement=True)
    circle_name_normalized = Column(String(255), unique=True, index=True)
    maker_id = Column(String(20), index=True, default='')
    kikoeru_circle_id = Column(String(32), index=True, default='')
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    def to_dict(self):
        return {
            'id': self.id,
            'circle_name_normalized': self.circle_name_normalized,
            'maker_id': self.maker_id or '',
            'kikoeru_circle_id': self.kikoeru_circle_id or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CircleWork(Base):
    """社团作品索引表"""
    __tablename__ = 'circle_works'

    id = Column(String(36), primary_key=True)
    circle_id = Column(String(120), index=True)
    canonical_rjcode = Column(String(20), index=True)
    display_rjcode = Column(String(20), index=True)
    title = Column(Text)
    maker_id = Column(String(20), index=True)
    maker_name = Column(Text)
    source_mask = Column(String(120), default='')
    linked_rjcodes = Column(JSON)
    has_kikoeru = Column(Boolean, default=False, index=True)
    kikoeru_found_rjcodes = Column(JSON)
    kikoeru_subtitle_rjcodes = Column(JSON)
    has_dlsite = Column(Boolean, default=False, index=True)
    has_asmr_one = Column(Boolean, default=False, index=True)
    asmr_available_rjcode = Column(String(20), index=True)
    kikoeru_work_id = Column(Integer)
    image_url = Column(String(500))
    price_text = Column(String(80))
    is_bonus_work = Column(Boolean, default=False, index=True)
    has_bonus = Column(Boolean, default=False, index=True)
    asmr_one_cached_at = Column(DateTime)
    dlsite_cached_at = Column(DateTime)
    source_tags = Column(JSON, default=list)  # 来源标签，如 ["email_watcher"]，用于"新作"标识
    # 邮件监听首次发现该作品的时间。专用字段，不会被 onupdate 刷新；
    # 配合 48h 窗口判定"是否仍属于新作"，避免被全量索引刷新 updated_at 后被误判。
    email_watcher_first_seen_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_circle_work_unique', 'circle_id', 'canonical_rjcode', unique=True),
        Index('idx_circle_works_circle_updated', 'circle_id', 'updated_at'),
        Index('idx_circle_works_circle_asmr', 'circle_id', 'has_asmr_one'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'circle_id': self.circle_id,
            'canonical_rjcode': self.canonical_rjcode,
            'display_rjcode': self.display_rjcode,
            'title': self.title,
            'maker_id': self.maker_id,
            'maker_name': self.maker_name,
            'source_mask': self.source_mask or '',
            'linked_rjcodes': self.linked_rjcodes or [],
            'has_kikoeru': bool(self.has_kikoeru),
            'kikoeru_found_rjcodes': self.kikoeru_found_rjcodes or [],
            'kikoeru_subtitle_rjcodes': self.kikoeru_subtitle_rjcodes or [],
            'has_dlsite': bool(self.has_dlsite),
            'has_asmr_one': bool(self.has_asmr_one),
            'asmr_available_rjcode': self.asmr_available_rjcode,
            'kikoeru_work_id': self.kikoeru_work_id,
            'image_url': self.image_url,
            'price_text': self.price_text or '',
            'is_bonus_work': bool(self.is_bonus_work),
            'has_bonus': bool(self.has_bonus),
            'asmr_one_cached_at': self.asmr_one_cached_at.isoformat() if self.asmr_one_cached_at else None,
            'dlsite_cached_at': self.dlsite_cached_at.isoformat() if self.dlsite_cached_at else None,
            'source_tags': self.source_tags or [],
            'email_watcher_first_seen_at': self.email_watcher_first_seen_at.isoformat() if self.email_watcher_first_seen_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkCanonicalLink(Base):
    """作品 canonical 归一关系"""
    __tablename__ = 'work_canonical_links'

    id = Column(String(36), primary_key=True)
    canonical_rjcode = Column(String(20), index=True)
    linked_rjcode = Column(String(20), index=True)
    link_type = Column(String(20), default='linked')
    lang = Column(String(20), default='')
    cached_at = Column(DateTime, default=get_local_now)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_work_canonical_unique', 'canonical_rjcode', 'linked_rjcode', unique=True),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'canonical_rjcode': self.canonical_rjcode,
            'linked_rjcode': self.linked_rjcode,
            'link_type': self.link_type,
            'lang': self.lang,
            'cached_at': self.cached_at.isoformat() if self.cached_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class LibraryOwnedWork(Base):
    """库存拥有态索引表"""
    __tablename__ = 'library_owned_works'

    canonical_rjcode = Column(String(20), primary_key=True)
    owned_rjcodes = Column(JSON)
    primary_folder_path = Column(Text)
    library_id = Column(String(80), index=True)
    folder_count = Column(Integer, default=0)
    folder_size = Column(BigInteger, default=0)
    file_count = Column(Integer, default=0)
    owned_paths = Column(JSON, default=list)
    has_local_subtitles = Column(Boolean, default=False, index=True)
    subtitle_file_count = Column(Integer, default=0)
    subtitle_dir = Column(Text)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    created_at = Column(DateTime, default=get_local_now)

    def to_dict(self):
        return {
            'canonical_rjcode': self.canonical_rjcode,
            'owned_rjcodes': self.owned_rjcodes or [],
            'primary_folder_path': self.primary_folder_path,
            'library_id': self.library_id,
            'folder_count': self.folder_count,
            'folder_size': int(self.folder_size or 0),
            'file_count': int(self.file_count or 0),
            'owned_paths': self.owned_paths or [],
            'has_local_subtitles': bool(self.has_local_subtitles),
            'subtitle_file_count': int(self.subtitle_file_count or 0),
            'subtitle_dir': self.subtitle_dir or '',
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class KikoeruSearchConfig(Base):
    """Kikoeru 搜索配置表"""
    __tablename__ = 'kikoeru_search_configs'
    
    id = Column(String(36), primary_key=True)
    name = Column(String(100), default='Kikoeru')  # 配置名称
    search_url_template = Column(Text)  # 搜索 URL 模板，如 http://xxx/api/search?keyword=%s
    show_url_template = Column(Text)   # 显示 URL 模板，如 http://xxx/works?keyword=%s
    enabled = Column(Boolean, default=False)
    custom_headers = Column(JSON, default=dict)  # 自定义请求头
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'search_url_template': self.search_url_template,
            'show_url_template': self.show_url_template,
            'enabled': self.enabled,
            'custom_headers': self.custom_headers or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class ProcessedArchive(Base):
    """已处理压缩包表"""
    __tablename__ = 'processed_archives'
    
    id = Column(String(36), primary_key=True)
    original_path = Column(Text)  # 原始路径
    current_path = Column(Text)   # 当前路径（在processed目录中）
    filename = Column(Text)       # 文件名
    rjcode = Column(String(20), index=True)  # RJ号
    file_size = Column(BigInteger)  # 文件大小
    volume_count = Column(Integer, default=1)  # 分卷数量，单文件为 1
    processed_at = Column(DateTime, default=get_local_now)  # 最后处理时间（本地时间）
    process_count = Column(Integer, default=1)  # 处理次数
    task_id = Column(String(36))  # 关联的任务ID
    status = Column(String(20), default='completed')  # completed, reprocessing
    
    __table_args__ = (
        Index('idx_filename', 'filename'),  # 文件名索引用于去重查询
    )
    
    def to_dict(self):
        """转换为字典"""
        # 修复：确保 processed_at 包含时区信息，避免前端把无时区 ISO 字符串当作 UTC 解析
        # 数据库中的 processed_at 是服务器本地时间，需要添加本地时区信息
        processed_at_str = None
        if self.processed_at:
            if self.processed_at.tzinfo is None:
                # 无时区信息，添加本地时区
                import time
                import os
                # 获取本地时区偏移（秒）
                if time.daylight and time.localtime().tm_isdst > 0:
                    offset_seconds = -time.altzone
                else:
                    offset_seconds = -time.timezone
                from datetime import timezone, timedelta
                local_tz = timezone(timedelta(seconds=offset_seconds))
                processed_at_str = self.processed_at.replace(tzinfo=local_tz).isoformat()
            else:
                processed_at_str = self.processed_at.isoformat()
        return {
            'id': self.id,
            'original_path': self.original_path,
            'current_path': self.current_path,
            'filename': self.filename,
            'rjcode': self.rjcode,
            'file_size': self.file_size,
            'volume_count': self.volume_count or 1,
            'processed_at': processed_at_str,
            'process_count': self.process_count,
            'task_id': self.task_id,
            'status': self.status
        }

class PasswordEntry(Base):
    """密码库表 - 存储解压密码"""
    __tablename__ = 'password_entries'
    
    id = Column(String(36), primary_key=True)
    rjcode = Column(String(20), index=True)  # RJ号（可选，用于关联作品）
    filename = Column(String(255), index=True)  # 文件名（可选，用于关联特定文件）
    password = Column(String(255), nullable=False)  # 密码
    description = Column(Text)  # 描述/备注
    source = Column(String(50), default='manual')  # 来源：manual手动, batch批量导入, auto自动提取
    use_count = Column(Integer, default=0)  # 使用次数
    last_used_at = Column(DateTime)  # 最后使用时间
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    
    __table_args__ = (
        Index('idx_password_rjcode', 'rjcode'),
        Index('idx_password_filename', 'filename'),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'rjcode': self.rjcode,
            'filename': self.filename,
            'password': self.password,
            'description': self.description,
            'source': self.source,
            'use_count': self.use_count,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class SecurityGateAuthLog(Base):
    """系统门禁认证记录"""
    __tablename__ = 'security_gate_auth_logs'

    id = Column(String(36), primary_key=True)
    event_type = Column(String(40), index=True)
    ip_address = Column(String(64), index=True)
    user_agent = Column(Text)
    path = Column(Text)
    success = Column(Boolean, default=False, index=True)
    failure_reason = Column(String(120), default='')
    code_length = Column(Integer, default=0)
    code_hint = Column(String(20), default='')
    triggered_blacklist = Column(Boolean, default=False)
    created_at = Column(DateTime, default=get_local_now, index=True)
    detail = Column(JSON, default=dict)

    def to_dict(self):
        return {
            'id': self.id,
            'event_type': self.event_type,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'path': self.path,
            'success': bool(self.success),
            'failure_reason': self.failure_reason or '',
            'code_length': int(self.code_length or 0),
            'code_hint': self.code_hint or '',
            'triggered_blacklist': bool(self.triggered_blacklist),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'detail': self.detail or {},
        }


class SecurityGateBlacklist(Base):
    """系统门禁黑名单"""
    __tablename__ = 'security_gate_blacklist'

    id = Column(String(36), primary_key=True)
    ip_address = Column(String(64), unique=True, index=True)
    reason = Column(Text)
    failure_count = Column(Integer, default=0)
    permanent = Column(Boolean, default=True)
    active = Column(Boolean, default=True, index=True)
    blocked_at = Column(DateTime, default=get_local_now, index=True)
    last_seen_at = Column(DateTime, default=get_local_now)
    unblocked_at = Column(DateTime)
    unblock_reason = Column(Text)

    def to_dict(self):
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'reason': self.reason or '',
            'failure_count': int(self.failure_count or 0),
            'permanent': bool(self.permanent),
            'active': bool(self.active),
            'blocked_at': self.blocked_at.isoformat() if self.blocked_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'unblocked_at': self.unblocked_at.isoformat() if self.unblocked_at else None,
            'unblock_reason': self.unblock_reason or '',
        }


class SecurityGateEmailThrottle(Base):
    """系统门禁邮件提醒限流"""
    __tablename__ = 'security_gate_email_throttle'

    throttle_key = Column(String(160), primary_key=True)
    last_sent_at = Column(DateTime, default=get_local_now)


class WatcherConfig(Base):
    """监视器配置表"""
    __tablename__ = 'watcher_config'

    id = Column(Integer, primary_key=True)
    watch_path = Column(Text)
    scan_interval = Column(Integer, default=30)
    auto_start = Column(Boolean, default=True)
    auto_classify = Column(Boolean, default=True)
    delete_after_process = Column(Boolean, default=False)
    is_running = Column(Boolean, default=False)

class PasswordCleanupLog(Base):
    """密码清理日志表"""
    __tablename__ = 'password_cleanup_logs'

    id = Column(String(36), primary_key=True)
    deleted_count = Column(Integer, default=0)  # 删除的密码数量
    config_snapshot = Column(JSON)  # 执行时的配置快照
    deleted_passwords_summary = Column(JSON)  # 删除的密码摘要（不包含完整密码）
    created_at = Column(DateTime, default=get_local_now)

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'deleted_count': self.deleted_count,
            'config_snapshot': self.config_snapshot,
            'deleted_passwords_summary': self.deleted_passwords_summary,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ProcessedArchiveCleanupLog(Base):
    """已处理压缩包清理日志表"""
    __tablename__ = 'processed_archive_cleanup_logs'

    id = Column(String(36), primary_key=True)
    deleted_count = Column(Integer, default=0)  # 删除的压缩包数量
    freed_space_bytes = Column(BigInteger, default=0)  # 释放的空间（字节）
    config_snapshot = Column(JSON)  # 执行时的配置快照
    deleted_archives_summary = Column(JSON)  # 删除的压缩包摘要
    created_at = Column(DateTime, default=get_local_now)

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'deleted_count': self.deleted_count,
            'freed_space_bytes': self.freed_space_bytes,
            'freed_space_mb': self.freed_space_bytes / (1024 * 1024) if self.freed_space_bytes else 0,
            'config_snapshot': self.config_snapshot,
            'deleted_archives_summary': self.deleted_archives_summary,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class BackupRecord(Base):
    """库存压缩备份记录表"""
    __tablename__ = 'backup_records'

    id = Column(String(36), primary_key=True)
    filename = Column(String(255), nullable=False)  # 压缩包文件名
    output_path = Column(Text, nullable=False)      # 输出路径
    source_path = Column(Text, nullable=False)      # 源路径
    
    pre_size_bytes = Column(BigInteger, default=0)  # 压缩前大小
    post_size_bytes = Column(BigInteger, default=0) # 压缩后大小
    compression_ratio = Column(Float, default=0)    # 压缩率 (0-1)
    
    duration_seconds = Column(Integer, default=0)   # 耗时（秒）
    status = Column(String(50), default='completed')# 状态: completed, failed
    error_message = Column(Text)                    # 错误信息
    
    # 统计信息
    speed_avg = Column(String(50))                  # 平均速度
    
    # 时间点
    backup_start_time = Column(DateTime)            # 记录文件名中标识的起始时间
    backup_end_time = Column(DateTime)              # 记录文件名中标识的结束时间
    created_at = Column(DateTime, default=get_local_now)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'output_path': self.output_path,
            'source_path': self.source_path,
            'pre_size_bytes': self.pre_size_bytes,
            'post_size_bytes': self.post_size_bytes,
            'compression_ratio': self.compression_ratio,
            'duration_seconds': self.duration_seconds,
            'status': self.status,
            'error_message': self.error_message,
            'speed_avg': self.speed_avg,
            'backup_start_time': self.backup_start_time.isoformat() if self.backup_start_time else None,
            'backup_end_time': self.backup_end_time.isoformat() if self.backup_end_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class BackupCheckpoint(Base):
    """压缩断点续传记录表"""
    __tablename__ = 'backup_checkpoints'

    id = Column(String(36), primary_key=True)
    source_path = Column(Text)
    output_dir = Column(Text)
    archive_path = Column(Text)
    archive_format = Column(String(10))
    compression_level = Column(Integer)
    password_hash = Column(String(64))
    file_manifest = Column(Text)          # JSON string
    completed_chunks = Column(Text)       # JSON string
    current_chunk_index = Column(Integer, default=0)
    total_chunks = Column(Integer)
    total_files = Column(Integer)
    processed_files = Column(Integer, default=0)
    total_bytes = Column(BigInteger, default=0)
    processed_bytes = Column(BigInteger, default=0)
    state = Column(String(20))           # in_progress / interrupted / completed
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

class WaitingRetryTask(Base):
    """等待重试任务表"""
    __tablename__ = 'waiting_retry_tasks'

    id = Column(String(36), primary_key=True)
    rjcode = Column(String(20))
    subtitle_folder = Column(Text)
    work_title = Column(Text)
    retry_reason = Column(Text)
    retry_count = Column(Integer, default=1)
    max_retry_count = Column(Integer, default=10)
    retry_after = Column(DateTime)  # 下次重试时间
    task_metadata = Column(JSON)  # 其他任务元数据
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'rjcode': self.rjcode,
            'subtitle_folder': self.subtitle_folder,
            'work_title': self.work_title,
            'retry_reason': self.retry_reason,
            'retry_count': self.retry_count,
            'max_retry_count': self.max_retry_count,
            'retry_after': self.retry_after.isoformat() if self.retry_after else None,
            'task_metadata': self.task_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class ActivityLog(Base):
    """用户操作审计表"""
    __tablename__ = 'activity_logs'

    id = Column(String(36), primary_key=True)
    category = Column(String(40))
    action = Column(String(80))
    status = Column(String(20))
    summary = Column(Text)
    detail = Column(JSON)
    rjcode = Column(String(32))
    task_id = Column(String(36))
    source_path = Column(Text)
    created_at = Column(DateTime, default=get_local_now)
    # Phase 2：从 detail JSON 提升上来的高频查询字段，建索引后替换掉合并时 O(B·N) 扫描
    batch_id = Column(String(80))
    session_key = Column(String(120))
    parent_id = Column(String(36))

    __table_args__ = (
        Index('idx_activity_created_category', 'created_at', 'category'),
        Index('idx_activity_category_batch', 'category', 'batch_id'),
        Index('idx_activity_category_session', 'category', 'session_key'),
        Index('idx_activity_status_created', 'status', 'created_at'),
        Index('idx_activity_category_status_created', 'category', 'status', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'action': self.action,
            'status': self.status,
            'summary': self.summary,
            'detail': self.detail or {},
            'rjcode': self.rjcode,
            'task_id': self.task_id,
            'source_path': self.source_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'batch_id': self.batch_id,
            'session_key': self.session_key,
            'parent_id': self.parent_id,
        }


class ActivityLogDailyStats(Base):
    """操作审计日聚合表（Phase 4A）。

    每条 activity_logs 写入时，Writer 会按 (date, category, status) 在这张表上做 UPSERT，
    把 count + 1 累加上去。图表接口不再需要在全表跑 GROUP BY。

    复合主键 (date, category, status)：date 为 'YYYY-MM-DD' 字符串。
    """
    __tablename__ = 'activity_log_daily_stats'

    date = Column(String(10), primary_key=True)
    category = Column(String(40), primary_key=True)
    status = Column(String(20), primary_key=True)
    count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_activity_daily_date', 'date'),
        Index('idx_activity_daily_category', 'category'),
    )


class ActivityLogRollup(Base):
    """操作审计轻量 rollup。

    当前阶段按 batch_id / session_key / task_id 三种稳定关联键维护计数和最新活动时间，
    用于替代列表期 N+1 子任务状态回查，并为后续深度树形物化提供基础数据。
    """
    __tablename__ = 'activity_log_rollups'

    rollup_key = Column(String(180), primary_key=True)
    rollup_type = Column(String(24), index=True)
    group_value = Column(String(140), index=True)
    category = Column(String(40), index=True)
    parent_log_id = Column(String(36), index=True)
    latest_log_id = Column(String(36))
    child_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    partial_count = Column(Integer, nullable=False, default=0)
    waiting_count = Column(Integer, nullable=False, default=0)
    latest_status = Column(String(24), default='')
    latest_activity_at = Column(DateTime, index=True)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_activity_rollup_type_value', 'rollup_type', 'group_value'),
        Index('idx_activity_rollup_category_status', 'category', 'latest_status'),
    )


class ASMRWork(Base):
    """ASMR 作品元信息表"""
    __tablename__ = 'asmr_works'

    rjcode = Column(String(20), primary_key=True)
    title = Column(Text)
    circle = Column(Text)
    source_provider = Column(String(40), default='asmr.one', index=True)
    tags = Column(JSON)
    work_status = Column(String(20), default='cataloged', index=True)
    last_error = Column(Text)
    last_scraped_at = Column(DateTime)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    def to_dict(self):
        return {
            'rjcode': self.rjcode,
            'title': self.title,
            'circle': self.circle,
            'source_provider': self.source_provider,
            'tags': self.tags or [],
            'work_status': self.work_status,
            'last_error': self.last_error,
            'last_scraped_at': self.last_scraped_at.isoformat() if self.last_scraped_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ASMRResourceRecord(Base):
    """ASMR 资源库表"""
    __tablename__ = 'asmr_resource_records'

    id = Column(String(36), primary_key=True)
    rjcode = Column(String(20))
    work_rjcode = Column(String(20), index=True)
    source_workno = Column(String(20), index=True)
    work_title = Column(Text)
    source_provider = Column(String(40), default='asmr.one', index=True)
    resource_type = Column(String(20), index=True)
    language = Column(String(16), default='')
    file_name = Column(Text)
    relative_path = Column(Text)
    normalized_name = Column(String(255), index=True)
    file_ext = Column(String(16), default='')
    size_bytes = Column(BigInteger, default=0)
    duration_seconds = Column(Float, nullable=True)
    checksum_md5 = Column(String(32), default='')
    remote_url = Column(Text)
    local_path = Column(Text)
    upload_path = Column(Text)
    download_status = Column(String(20), default='cataloged')
    match_status = Column(String(20), default='unmatched', index=True)
    verify_status = Column(String(20), default='pending', index=True)
    upload_status = Column(String(20), default='pending', index=True)
    missing_reason = Column(String(120))
    session_id = Column(String(36))
    retry_count = Column(Integer, default=0)
    last_seen_at = Column(DateTime, default=get_local_now, index=True)
    last_error = Column(Text)
    extra_metadata = Column(JSON)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_asmr_resource_unique', 'rjcode', 'source_provider', 'relative_path'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'rjcode': self.rjcode,
            'work_rjcode': self.work_rjcode,
            'source_workno': self.source_workno,
            'work_title': self.work_title,
            'source_provider': self.source_provider,
            'resource_type': self.resource_type,
            'language': self.language,
            'file_name': self.file_name,
            'relative_path': self.relative_path,
            'normalized_name': self.normalized_name,
            'file_ext': self.file_ext,
            'size_bytes': self.size_bytes,
            'duration_seconds': self.duration_seconds,
            'checksum_md5': self.checksum_md5,
            'remote_url': self.remote_url,
            'local_path': self.local_path,
            'upload_path': self.upload_path,
            'download_status': self.download_status,
            'match_status': self.match_status,
            'verify_status': self.verify_status,
            'upload_status': self.upload_status,
            'missing_reason': self.missing_reason,
            'session_id': self.session_id,
            'retry_count': self.retry_count,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'last_error': self.last_error,
            'extra_metadata': self.extra_metadata or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ASMRDownloadSession(Base):
    """ASMR 增强下载会话表"""
    __tablename__ = 'asmr_download_sessions'

    id = Column(String(36), primary_key=True)
    rjcode = Column(String(20))
    task_id = Column(String(36), index=True)
    source_provider = Column(String(40), default='asmr.one', index=True)
    source_page = Column(String(40), default='asmr-sync')
    source_action = Column(String(80), default='enhanced_download')
    source_label = Column(Text)
    status = Column(String(20), default='planning')
    queue_priority = Column(Integer, default=100)
    folder_path = Column(Text)
    target_path = Column(Text)
    upload_mode = Column(String(20), default='disabled')
    selected_filters = Column(JSON)
    selected_resources = Column(JSON)
    statistics = Column(JSON)
    failure_summary = Column(JSON)
    local_download_ready = Column(Boolean, default=False, index=True)
    local_download_root = Column(Text)
    local_downloaded_count = Column(Integer, default=0)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_asmr_download_sessions_rj_updated', 'rjcode', 'updated_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'rjcode': self.rjcode,
            'task_id': self.task_id,
            'source_provider': self.source_provider,
            'source_page': self.source_page,
            'source_action': self.source_action,
            'source_label': self.source_label,
            'status': self.status,
            'queue_priority': self.queue_priority,
            'folder_path': self.folder_path,
            'target_path': self.target_path,
            'upload_mode': self.upload_mode,
            'selected_filters': self.selected_filters or {},
            'selected_resources': self.selected_resources or [],
            'statistics': self.statistics or {},
            'failure_summary': self.failure_summary or {},
            'local_download_ready': bool(self.local_download_ready),
            'local_download_root': self.local_download_root,
            'local_downloaded_count': int(self.local_downloaded_count or 0),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

import logging
_db_logger = logging.getLogger(__name__)

_SLOW_SQL_DEBUG_THRESHOLD_SECONDS = float(os.getenv("KIKOERUMANAGER_SLOW_SQL_SECONDS", "0.2") or 0.2)
_SLOW_SQL_WARNING_THRESHOLD_SECONDS = float(os.getenv("KIKOERUMANAGER_SLOW_SQL_WARNING_SECONDS", "1.0") or 1.0)
_SLOW_SQL_LOG_THRESHOLD_SECONDS = _SLOW_SQL_WARNING_THRESHOLD_SECONDS
_SLOW_SQL_MAX_TEXT_LEN = 320
_SLOW_SQL_MAX_PARAM_ITEMS = 8


def _compact_sql_for_log(statement: Any) -> str:
    text_value = " ".join(str(statement or "").split())
    if len(text_value) <= _SLOW_SQL_MAX_TEXT_LEN:
        return text_value
    return text_value[:_SLOW_SQL_MAX_TEXT_LEN] + "..."


def _summarize_sql_param(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, bytes):
        return f"bytes[{len(value)}]"
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, (list, tuple, set)):
        return f"{type(value).__name__}[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


def _summarize_sql_params(parameters: Any) -> Any:
    if parameters in (None, (), [], {}):
        return None
    try:
        if isinstance(parameters, dict):
            items = list(parameters.items())[:_SLOW_SQL_MAX_PARAM_ITEMS]
            result = {str(key): _summarize_sql_param(value) for key, value in items}
            if len(parameters) > _SLOW_SQL_MAX_PARAM_ITEMS:
                result["..."] = f"+{len(parameters) - _SLOW_SQL_MAX_PARAM_ITEMS}"
            return result
        if isinstance(parameters, (list, tuple)):
            items = list(parameters)[:_SLOW_SQL_MAX_PARAM_ITEMS]
            result = [_summarize_sql_param(value) for value in items]
            if len(parameters) > _SLOW_SQL_MAX_PARAM_ITEMS:
                result.append(f"+{len(parameters) - _SLOW_SQL_MAX_PARAM_ITEMS}")
            return result
        return _summarize_sql_param(parameters)
    except Exception:
        return type(parameters).__name__


def _effective_slow_sql_warning_threshold() -> float:
    values = [
        float(value)
        for value in (
            _SLOW_SQL_WARNING_THRESHOLD_SECONDS,
            globals().get("_SLOW_SQL_LOG_THRESHOLD_SECONDS", _SLOW_SQL_WARNING_THRESHOLD_SECONDS),
        )
        if float(value) > 0
    ]
    return min(values) if values else 0.0


def _slow_sql_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    warning_threshold = _effective_slow_sql_warning_threshold()
    if _SLOW_SQL_DEBUG_THRESHOLD_SECONDS <= 0 and warning_threshold <= 0:
        return
    context._kikoerumanager_sql_started_at = time.perf_counter()


def _slow_sql_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    warning_threshold = _effective_slow_sql_warning_threshold()
    if _SLOW_SQL_DEBUG_THRESHOLD_SECONDS <= 0 and warning_threshold <= 0:
        return
    started_at = getattr(context, "_kikoerumanager_sql_started_at", None)
    if not started_at:
        return
    elapsed = time.perf_counter() - started_at
    active_thresholds = [
        threshold
        for threshold in (_SLOW_SQL_DEBUG_THRESHOLD_SECONDS, warning_threshold)
        if threshold > 0
    ]
    if not active_thresholds or elapsed < min(active_thresholds):
        return
    log_method = (
        _db_logger.warning
        if warning_threshold > 0 and elapsed >= warning_threshold
        else _db_logger.debug
    )
    log_method(
        "[数据库] 慢 SQL %.3fs executemany=%s rowcount=%s sql=%s params=%s",
        elapsed,
        bool(executemany),
        getattr(cursor, "rowcount", None),
        _compact_sql_for_log(statement),
        _summarize_sql_params(parameters),
    )

class NotificationTemplate(Base):
    """通知邮件模板表"""
    __tablename__ = 'notification_templates'

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    channel = Column(String(20), default='email')
    event_types = Column(JSON, default=list)
    task_domains = Column(JSON, default=list)
    editor_mode = Column(String(20), default='html')
    blocks = Column(JSON, default=list)
    subject_template = Column(Text, default='')
    html_template = Column(Text, default='')
    text_template = Column(Text, default='')
    enabled = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    description = Column(Text, default='')
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'channel': self.channel,
            'event_types': self.event_types or [],
            'task_domains': self.task_domains or [],
            'editor_mode': self.editor_mode,
            'blocks': self.blocks or [],
            'subject_template': self.subject_template or '',
            'html_template': self.html_template or '',
            'text_template': self.text_template or '',
            'enabled': bool(self.enabled),
            'is_default': bool(self.is_default),
            'sort_order': self.sort_order or 0,
            'description': self.description or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationInboxItem(Base):
    """站内通知收件箱表"""
    __tablename__ = 'notification_inbox_items'

    id = Column(String(36), primary_key=True)
    event_key = Column(String(200), unique=True, index=True)
    event_type = Column(String(40), index=True)
    severity = Column(String(20), default='info')
    group_key = Column(String(200), index=True)
    group_type = Column(String(40), default='task')
    group_run_id = Column(String(80), default='')
    primary_task_id = Column(String(36), index=True)
    task_ids = Column(JSON, default=list)
    session_id = Column(String(80), default='')
    parent_session_id = Column(String(80), default='')
    batch_id = Column(String(80), default='')
    task_domain = Column(String(60), default='')
    task_kind = Column(String(60), default='')
    source_page = Column(String(60), default='')
    source_action = Column(String(80), default='')
    source_label = Column(Text, default='')
    business_key = Column(String(120), default='')
    title = Column(Text, default='')
    summary = Column(Text, default='')
    rjcode = Column(String(20), default='')
    route_path = Column(String(200), default='')
    route_query = Column(JSON, default=dict)
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime)
    created_at = Column(DateTime, default=get_local_now, index=True)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_notification_inbox_created', 'created_at'),
        Index('idx_notification_inbox_unread', 'is_read', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'event_key': self.event_key,
            'event_type': self.event_type,
            'severity': self.severity,
            'group_key': self.group_key,
            'group_type': self.group_type,
            'group_run_id': self.group_run_id or '',
            'primary_task_id': self.primary_task_id,
            'task_ids': self.task_ids or [],
            'session_id': self.session_id or '',
            'parent_session_id': self.parent_session_id or '',
            'batch_id': self.batch_id or '',
            'task_domain': self.task_domain or '',
            'task_kind': self.task_kind or '',
            'source_page': self.source_page or '',
            'source_action': self.source_action or '',
            'source_label': self.source_label or '',
            'business_key': self.business_key or '',
            'title': self.title or '',
            'summary': self.summary or '',
            'rjcode': self.rjcode or '',
            'route_path': self.route_path or '',
            'route_query': self.route_query or {},
            'is_read': bool(self.is_read),
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationOutbox(Base):
    """通知邮件发送 outbox 表（异步发件队列）"""
    __tablename__ = 'notification_outbox'

    id = Column(String(36), primary_key=True)
    inbox_item_id = Column(String(36), index=True)
    event_key = Column(String(200), index=True)
    channel = Column(String(20), default='email')
    status = Column(String(20), default='pending', index=True)
    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime)
    last_error = Column(Text)
    payload = Column(JSON, default=dict)
    sent_at = Column(DateTime)
    created_at = Column(DateTime, default=get_local_now, index=True)

    __table_args__ = (
        Index('idx_notification_outbox_status', 'status', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'inbox_item_id': self.inbox_item_id,
            'event_key': self.event_key,
            'channel': self.channel,
            'status': self.status,
            'attempt_count': self.attempt_count,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'last_error': self.last_error,
            'payload': self.payload or {},
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class LibraryIndexEntry(Base):
    """库存搜索索引表（library_index 模块专用）。

    为"本地搜索文件路径 / 统计文件夹大小"业务专门建立的常驻索引。
    数据来源：
    - local 库存走 os.scandir 全量扫 + watchdog 增量维护
    - synology_filestation 库存走 SYNO.FileStation.Search 快照 + 定期 rescan

    设计要点：
    - (library_id, relative_path) 作为自然主键保证幂等
    - 运行期只随表创建唯一索引；RJ / 名称 / 子树路径索引由 PostgreSQL 后台 CONCURRENTLY 维护
    - 目录行 size 存递归大小，避免运行时反复 os.walk
    - 与 LibrarySnapshot 不冲突：LibrarySnapshot 是业务缓存（按 RJ 号单射），
      这张表是搜索索引（按多库存 + 完整路径组织）。
    """
    __tablename__ = 'library_index_entries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(String(60), nullable=False)
    entry_type = Column(String(10), nullable=False)  # 'dir' / 'file'
    relative_path = Column(Text, nullable=False)
    absolute_path = Column(Text, nullable=False)
    name = Column(String(255), nullable=False)
    name_sort_key = Column(Text, nullable=False, default='')
    rjcode = Column(String(20))
    parent_path = Column(Text)
    size = Column(BigInteger, default=0)
    file_count = Column(Integer, default=0)
    mtime = Column(BigInteger)  # 毫秒时间戳
    depth = Column(Integer)
    indexed_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('idx_lie_library_rel', 'library_id', 'relative_path', unique=True),
    )


class LibraryIndexStatus(Base):
    """库存搜索索引状态表。

    每个 library_id 一行，跟踪索引的构建 / 失效 / 运行模式。
    """
    __tablename__ = 'library_index_status'

    library_id = Column(String(60), primary_key=True)
    # 'idle' / 'syncing' / 'ready' / 'error' / 'disabled'
    status = Column(String(20), nullable=False, default='idle')
    # 'watchdog' / 'polling' / 'remote_rescan' / 'disabled'
    watcher_mode = Column(String(30))
    last_full_scan_at = Column(BigInteger)
    last_event_at = Column(BigInteger)
    total_entries = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)
    folder_count = Column(Integer, default=0)
    error = Column(Text)
    updated_at = Column(BigInteger, nullable=False)

    def to_dict(self):
        return {
            'library_id': self.library_id,
            'status': self.status,
            'watcher_mode': self.watcher_mode,
            'last_full_scan_at': self.last_full_scan_at,
            'last_event_at': self.last_event_at,
            'total_entries': int(self.total_entries or 0),
            'total_size_bytes': int(self.total_size_bytes or 0),
            'folder_count': int(self.folder_count or 0),
            'error': self.error,
            'updated_at': int(self.updated_at or 0),
        }


class PikPakStatusCache(Base):
    """PikPak 账号状态持久缓存。

    只存前端展示需要的公开统计快照，不存密码、token、直链等敏感信息。
    """
    __tablename__ = 'pikpak_status_cache'

    account_id = Column(String(80), primary_key=True)
    account_label = Column(String(255), nullable=False, default='')
    username_hint = Column(String(255), nullable=False, default='')
    transfer_dir = Column(Text, nullable=False, default='/KikoeruManager')
    success = Column(Boolean, nullable=False, default=False)
    ready = Column(Boolean, nullable=False, default=False)
    quota = Column(JSON, default=dict)
    transfer_quota = Column(JSON, default=dict)
    vip = Column(JSON, default=dict)
    message = Column(Text, default='')
    source = Column(String(20), nullable=False, default='live')
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_pikpak_status_cache_updated_at', 'updated_at'),
    )

    def to_status_dict(self) -> Dict[str, Any]:
        account = {
            'id': self.account_id,
            'label': self.account_label,
            'username': self.username_hint,
            'enabled': True,
            'transfer_dir': self.transfer_dir or '/KikoeruManager',
            'legacy': self.account_id == 'default',
            'configured': True,
        }
        updated_at = self.updated_at.isoformat() if self.updated_at else None
        return {
            'success': bool(self.success),
            'enabled': True,
            'ready': bool(self.ready),
            'account': account,
            'account_id': self.account_id,
            'account_label': self.account_label,
            'transfer_dir': self.transfer_dir or '/KikoeruManager',
            'quota': self.quota or {},
            'transfer_quota': self.transfer_quota or {},
            'vip': self.vip or {},
            'message': self.message or '',
            'source': self.source or 'cache',
            'cached': True,
            'updated_at': updated_at,
            'cache_updated_at': updated_at,
        }


class AISubtitleMatchUsage(Base):
    """AI 字幕配对请求摘要。只存计数和错误摘要，不落完整 prompt/response。"""
    __tablename__ = 'ai_subtitle_match_usage'

    id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, default=get_local_now, index=True)
    task_id = Column(String(36), index=True)
    rjcode = Column(String(20), index=True)
    mode = Column(String(30), nullable=False, default='')
    model = Column(String(120), nullable=False, default='')
    request_hash = Column(String(80), index=True)
    audio_count = Column(Integer, default=0)
    subtitle_group_count = Column(Integer, default=0)
    matched_count = Column(Integer, default=0)
    low_confidence_count = Column(Integer, default=0)
    unmatched_audio_count = Column(Integer, default=0)
    unmatched_subtitle_count = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    status = Column(String(20), nullable=False, default='')
    error_summary = Column(Text, default='')
    auto_applied = Column(Boolean, default=False)

    __table_args__ = (
        Index('idx_ai_subtitle_usage_task_created', 'task_id', 'created_at'),
        Index('idx_ai_subtitle_usage_rj_created', 'rjcode', 'created_at'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'task_id': self.task_id or '',
            'rjcode': self.rjcode or '',
            'mode': self.mode or '',
            'model': self.model or '',
            'request_hash': self.request_hash or '',
            'audio_count': int(self.audio_count or 0),
            'subtitle_group_count': int(self.subtitle_group_count or 0),
            'matched_count': int(self.matched_count or 0),
            'low_confidence_count': int(self.low_confidence_count or 0),
            'unmatched_audio_count': int(self.unmatched_audio_count or 0),
            'unmatched_subtitle_count': int(self.unmatched_subtitle_count or 0),
            'prompt_tokens': int(self.prompt_tokens or 0),
            'completion_tokens': int(self.completion_tokens or 0),
            'total_tokens': int(self.total_tokens or 0),
            'duration_ms': int(self.duration_ms or 0),
            'status': self.status or '',
            'error_summary': self.error_summary or '',
            'auto_applied': bool(self.auto_applied),
        }


# 数据库连接

def _mask_database_url(value: str) -> str:
    if not value:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(value)
        if not parts.password:
            return value
        username = parts.username or ""
        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        auth = f"{username}:********@" if username else "********@"
        netloc = f"{auth}{hostname}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "postgresql+psycopg://********"


def _build_database_url_from_config() -> str:
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        if not env_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("DATABASE_URL 必须使用 postgresql+psycopg:// 前缀")
        return env_url

    from urllib.parse import quote_plus

    try:
        from ..config.settings import get_config

        cfg = getattr(get_config(), "database", None)
    except Exception as exc:
        raise RuntimeError(f"读取 PostgreSQL 配置失败: {exc}") from exc

    host = str(getattr(cfg, "host", "127.0.0.1") or "127.0.0.1").strip()
    port = int(getattr(cfg, "port", 5432) or 5432)
    database = str(getattr(cfg, "database", "kikoerumanager") or "kikoerumanager").strip()
    username = str(getattr(cfg, "username", "kikoerumanager") or "kikoerumanager").strip()
    password = str(getattr(cfg, "password", "") or "")
    sslmode = str(getattr(cfg, "sslmode", "prefer") or "prefer").strip()
    if not host or not database or not username:
        raise RuntimeError("PostgreSQL 配置缺少 host/database/username")
    auth = quote_plus(username)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    query = f"?sslmode={quote_plus(sslmode)}" if sslmode else ""
    return f"postgresql+psycopg://{auth}@{host}:{port}/{quote_plus(database)}{query}"


def _load_database_config() -> Dict[str, Any]:
    defaults = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "kikoerumanager",
        "username": "kikoerumanager",
        "password": "",
        "sslmode": "prefer",
        "connect_timeout_seconds": 10,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle_seconds": 1800,
        "pool_timeout_seconds": 30,
        "statement_timeout_ms": 120000,
        "startup_health_check": True,
    }
    try:
        from ..config.settings import get_config

        cfg = getattr(get_config(), "database", None)
        payload = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg or {})
        merged = {**defaults, **(payload or {})}
    except Exception:
        merged = dict(defaults)

    merged["port"] = max(1, min(65535, int(merged.get("port") or 5432)))
    merged["connect_timeout_seconds"] = max(1, int(merged.get("connect_timeout_seconds") or 10))
    merged["pool_size"] = max(1, int(merged.get("pool_size") or 10))
    merged["max_overflow"] = max(0, int(merged.get("max_overflow") or 20))
    merged["pool_recycle_seconds"] = max(60, int(merged.get("pool_recycle_seconds") or 1800))
    merged["pool_timeout_seconds"] = max(1, int(merged.get("pool_timeout_seconds") or 30))
    merged["statement_timeout_ms"] = max(1000, int(merged.get("statement_timeout_ms") or 120000))
    merged["startup_health_check"] = bool(merged.get("startup_health_check", True))
    return merged


_DATABASE_URL = _build_database_url_from_config()
_DB_RUNTIME_CONFIG = _load_database_config()


def _connect_args() -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "connect_timeout": _DB_RUNTIME_CONFIG["connect_timeout_seconds"],
    }
    timeout_ms = int(_DB_RUNTIME_CONFIG.get("statement_timeout_ms") or 120000)
    if timeout_ms > 0:
        args["options"] = f"-c statement_timeout={timeout_ms}"
    return args


engine = create_engine(
    _DATABASE_URL,
    connect_args=_connect_args(),
    poolclass=QueuePool,
    pool_size=_DB_RUNTIME_CONFIG["pool_size"],
    max_overflow=_DB_RUNTIME_CONFIG["max_overflow"],
    pool_recycle=_DB_RUNTIME_CONFIG["pool_recycle_seconds"],
    pool_timeout=_DB_RUNTIME_CONFIG["pool_timeout_seconds"],
    pool_pre_ping=True,
    json_serializer=_orjson_dumps,
    json_deserializer=_orjson_loads,
    echo=False,
)


@event.listens_for(engine, "connect")
def _postgres_on_connect(dbapi_connection, connection_record):
    # statement_timeout 已通过 libpq options 注入。这里不要再执行 SET：
    # psycopg3 下 SET 不能用参数占位，失败后会把新连接留在 aborted transaction，
    # 后续第一个真实查询会随机报 InFailedSqlTransaction。
    return


_POSTGRES_FATAL_ERROR_MARKERS = (
    "terminating connection",
    "server closed the connection",
    "connection not open",
    "connection refused",
)


@event.listens_for(engine, "handle_error")
def _postgres_handle_error(exception_context):
    original = getattr(exception_context, "original_exception", None)
    message = str(original or exception_context.sqlalchemy_exception or "").lower()
    if not any(marker in message for marker in _POSTGRES_FATAL_ERROR_MARKERS):
        return
    try:
        exception_context.is_disconnect = True
    except Exception:
        pass
    _db_logger.critical(
        "[数据库] 检测到 PostgreSQL 连接致命错误，已标记连接失效并释放连接池: url=%s error=%s",
        _mask_database_url(_DATABASE_URL),
        original or exception_context.sqlalchemy_exception,
    )
    try:
        engine.dispose()
    except Exception:
        _db_logger.debug("[数据库] dispose 连接池失败", exc_info=True)


event.listen(engine, "before_cursor_execute", _slow_sql_before_cursor_execute)
event.listen(engine, "after_cursor_execute", _slow_sql_after_cursor_execute)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_init_db_lock = threading.RLock()
_init_db_done = False
_library_index_maintenance_lock = threading.Lock()
_library_index_maintenance_thread: Optional[threading.Thread] = None


def _human_bytes(n: int) -> str:
    n = int(n or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(abs(n))
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    sign = "-" if n < 0 else ""
    return f"{sign}{int(value)} {units[idx]}" if idx == 0 else f"{sign}{value:.2f} {units[idx]}"


def _pg_table_size(conn, table_name: str) -> int:
    try:
        return int(conn.execute(text("SELECT pg_total_relation_size(to_regclass(:name))"), {"name": table_name}).scalar() or 0)
    except Exception:
        return 0


_POSTGRES_BUSINESS_INDEX_SPECS = (
    # 操作历史：列表常按 category + created_at 倒序取窗口；detail.session_id 用于详情关联子项。
    {
        "name": "idx_activity_category_created_desc",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_category_created_desc ON activity_logs(category, created_at DESC)",
        "fragments": ("activity_logs", "category", "created_at DESC"),
    },
    {
        "name": "idx_activity_detail_session_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_detail_session_id ON activity_logs((detail ->> 'session_id'))",
        "fragments": ("activity_logs", "detail ->> 'session_id'",),
    },
    {
        "name": "idx_activity_batch_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_batch_created ON activity_logs(batch_id, created_at DESC)",
        "fragments": ("activity_logs", "batch_id", "created_at DESC"),
    },
    {
        "name": "idx_activity_session_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_session_created ON activity_logs(session_key, created_at DESC)",
        "fragments": ("activity_logs", "session_key", "created_at DESC"),
    },
    {
        "name": "idx_activity_parent_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_parent_created ON activity_logs(parent_id, created_at DESC)",
        "fragments": ("activity_logs", "parent_id", "created_at DESC"),
    },
    {
        "name": "idx_activity_task_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_task_created ON activity_logs(task_id, created_at DESC)",
        "fragments": ("activity_logs", "task_id", "created_at DESC"),
    },
    {
        "name": "idx_activity_rj_category_status_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_rj_category_status_created ON activity_logs(rjcode, category, status, created_at DESC)",
        "fragments": ("activity_logs", "rjcode", "category", "status", "created_at DESC"),
    },
    {
        "name": "idx_activity_compact_scan",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_compact_scan ON activity_logs(created_at ASC, id ASC)",
        "fragments": ("activity_logs", "created_at", "id"),
    },
    # 问题作品列表、数量和处理链路：PENDING / PROCESSING 是最高频过滤，created_at 用于稳定新旧排序。
    {
        "name": "idx_conflict_active_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_conflict_active_created ON conflict_works(created_at DESC) WHERE status IN ('PENDING', 'PROCESSING') AND conflict_type <> 'LINKED_SUBTITLE_IMPORT'",
        "fragments": ("conflict_works", "created_at DESC", "PENDING", "PROCESSING", "LINKED_SUBTITLE_IMPORT"),
    },
    {
        "name": "idx_conflict_task_status",
        "sql": "CREATE INDEX IF NOT EXISTS idx_conflict_task_status ON conflict_works(task_id, status)",
        "fragments": ("conflict_works", "task_id", "status"),
    },
    {
        "name": "idx_conflict_rj_type_status",
        "sql": "CREATE INDEX IF NOT EXISTS idx_conflict_rj_type_status ON conflict_works(rjcode, conflict_type, status)",
        "fragments": ("conflict_works", "rjcode", "conflict_type", "status"),
    },
    # 任务中心：高频列表页按 domain/status 过滤后按更新时间倒序翻页；单任务详情按 engine_task_id 取最新物化快照。
    {
        "name": "idx_task_center_domain_status_updated_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_domain_status_updated_created ON task_center_items(domain, status, updated_at DESC, created_at DESC)",
        "fragments": ("task_center_items", "domain", "status", "updated_at DESC", "created_at DESC"),
    },
    {
        "name": "idx_task_center_domain_updated_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_domain_updated_created ON task_center_items(domain, updated_at DESC, created_at DESC)",
        "fragments": ("task_center_items", "domain", "updated_at DESC", "created_at DESC"),
    },
    {
        "name": "idx_task_center_status_updated_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_status_updated_created ON task_center_items(status, updated_at DESC, created_at DESC)",
        "fragments": ("task_center_items", "status", "updated_at DESC", "created_at DESC"),
    },
    {
        "name": "idx_task_center_updated_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_updated_created ON task_center_items(updated_at DESC, created_at DESC)",
        "fragments": ("task_center_items", "updated_at DESC", "created_at DESC"),
    },
    {
        "name": "idx_task_center_engine_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_engine_updated ON task_center_items(engine_task_id, updated_at DESC)",
        "fragments": ("task_center_items", "engine_task_id", "updated_at DESC"),
    },
    # ASMR 同步/资源面板：状态统计与最新资源/会话。
    {
        "name": "idx_asmr_resource_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_resource_updated ON asmr_resource_records(updated_at DESC)",
        "fragments": ("asmr_resource_records", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_resource_download_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_resource_download_updated ON asmr_resource_records(download_status, updated_at DESC)",
        "fragments": ("asmr_resource_records", "download_status", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_resource_session_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_resource_session_updated ON asmr_resource_records(session_id, updated_at DESC)",
        "fragments": ("asmr_resource_records", "session_id", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_resource_rj_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_resource_rj_updated ON asmr_resource_records(rjcode, updated_at DESC)",
        "fragments": ("asmr_resource_records", "rjcode", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_session_status_priority_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_session_status_priority_updated ON asmr_download_sessions(status, queue_priority, updated_at DESC)",
        "fragments": ("asmr_download_sessions", "status", "queue_priority", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_session_priority_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_session_priority_updated ON asmr_download_sessions(queue_priority, updated_at DESC)",
        "fragments": ("asmr_download_sessions", "queue_priority", "updated_at DESC"),
    },
    {
        "name": "idx_asmr_session_updated",
        "sql": "CREATE INDEX IF NOT EXISTS idx_asmr_session_updated ON asmr_download_sessions(updated_at DESC)",
        "fragments": ("asmr_download_sessions", "updated_at DESC"),
    },
    # 已处理压缩包：历史列表、重处理回查、智能清理都围绕 processed_at / task_id / status。
    {
        "name": "idx_processed_archives_processed_at_desc",
        "sql": "CREATE INDEX IF NOT EXISTS idx_processed_archives_processed_at_desc ON processed_archives(processed_at DESC)",
        "fragments": ("processed_archives", "processed_at DESC"),
    },
    {
        "name": "idx_processed_archives_task_processed",
        "sql": "CREATE INDEX IF NOT EXISTS idx_processed_archives_task_processed ON processed_archives(task_id, processed_at DESC)",
        "fragments": ("processed_archives", "task_id", "processed_at DESC"),
    },
    {
        "name": "idx_processed_archives_status_processed",
        "sql": "CREATE INDEX IF NOT EXISTS idx_processed_archives_status_processed ON processed_archives(status, processed_at ASC)",
        "fragments": ("processed_archives", "status", "processed_at"),
    },
    # 密码工作台：rjcode 保存有大小写差异时，upper(rjcode) 合并命中仍能走索引。
    {
        "name": "idx_password_upper_rjcode",
        "sql": "CREATE INDEX IF NOT EXISTS idx_password_upper_rjcode ON password_entries(upper(rjcode))",
        "fragments": ("password_entries", "upper", "rjcode"),
    },
)


_POSTGRES_LIBRARY_INDEX_SPECS = (
    # 库存索引：几十万行级别的大表索引，启动时不在事务里阻塞创建，改由后台 CONCURRENTLY 维护。
    {
        "name": "idx_lie_rj_lookup",
        "sql": (
            "CREATE INDEX IF NOT EXISTS idx_lie_rj_lookup "
            "ON library_index_entries(rjcode, depth, relative_path, library_id, entry_type) "
            "WHERE rjcode IS NOT NULL"
        ),
        "fragments": ("library_index_entries", "rjcode", "depth", "relative_path", "library_id", "entry_type", "WHERE", "rjcode IS NOT NULL"),
    },
    {
        "name": "idx_lie_rj_prefix",
        "sql": (
            "CREATE INDEX IF NOT EXISTS idx_lie_rj_prefix "
            "ON library_index_entries(rjcode varchar_pattern_ops, depth, relative_path, library_id, entry_type) "
            "WHERE rjcode IS NOT NULL"
        ),
        "fragments": ("library_index_entries", "rjcode", "varchar_pattern_ops", "depth", "relative_path", "library_id", "entry_type", "WHERE", "rjcode IS NOT NULL"),
    },
    {
        "name": "idx_lie_indexed_at_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_indexed_at_id ON library_index_entries(library_id, indexed_at, id)",
        "fragments": ("library_index_entries", "library_id", "indexed_at", "id"),
    },
    {
        "name": "idx_lie_children_name",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_children_name ON library_index_entries(library_id, parent_path, name_sort_key, relative_path)",
        "fragments": ("library_index_entries", "library_id", "parent_path", "name_sort_key", "relative_path"),
    },
    {
        "name": "idx_lie_children_size",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_children_size ON library_index_entries(library_id, parent_path, size, name_sort_key, relative_path)",
        "fragments": ("library_index_entries", "library_id", "parent_path", "size", "name_sort_key", "relative_path"),
    },
    {
        "name": "idx_lie_children_size_desc",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_children_size_desc ON library_index_entries(library_id, parent_path, size DESC, name_sort_key, relative_path)",
        "fragments": ("library_index_entries", "library_id", "parent_path", "size DESC", "name_sort_key", "relative_path"),
    },
    {
        "name": "idx_lie_children_time",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_children_time ON library_index_entries(library_id, parent_path, mtime, name_sort_key, relative_path)",
        "fragments": ("library_index_entries", "library_id", "parent_path", "mtime", "name_sort_key", "relative_path"),
    },
    {
        "name": "idx_lie_children_time_desc",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_children_time_desc ON library_index_entries(library_id, parent_path, mtime DESC NULLS LAST, name_sort_key, relative_path)",
        "fragments": ("library_index_entries", "library_id", "parent_path", "mtime DESC", "NULLS LAST", "name_sort_key", "relative_path"),
    },
    {
        "name": "idx_lie_subtree_path_pattern",
        "sql": "CREATE INDEX IF NOT EXISTS idx_lie_subtree_path_pattern ON library_index_entries(library_id, relative_path text_pattern_ops)",
        "fragments": ("library_index_entries", "library_id", "relative_path", "text_pattern_ops"),
    },
)


_POSTGRES_OBSOLETE_INDEX_NAMES = (
    # 任务中心迁移期遗留索引；已由下方 domain/status/updated_at 复合索引和 trigram 搜索索引覆盖。
    "idx_task_center_items_domain_status",
    "idx_task_center_items_updated_at",
    "ix_task_center_items_business_key",
    "ix_task_center_items_created_at",
    "ix_task_center_items_domain",
    "ix_task_center_items_engine_task_id",
    "ix_task_center_items_status",
    "ix_task_center_items_updated_at",
    # 操作历史：单列索引已被业务复合索引覆盖，保留它们只会放大 append-only 写入成本。
    "ix_activity_logs_batch_id",
    "ix_activity_logs_category",
    "ix_activity_logs_created_at",
    "ix_activity_logs_parent_id",
    "ix_activity_logs_rjcode",
    "ix_activity_logs_session_key",
    "ix_activity_logs_status",
    "ix_activity_logs_task_id",
    # ASMR 资源/会话：旧单列索引会拖慢批量资源 upsert，复合索引覆盖高频列表、统计和详情路径。
    "idx_asmr_resource_status",
    "ix_asmr_resource_records_download_status",
    "ix_asmr_resource_records_rjcode",
    "ix_asmr_resource_records_session_id",
    "ix_asmr_download_sessions_queue_priority",
    "ix_asmr_download_sessions_rjcode",
    "ix_asmr_download_sessions_status",
)


_POSTGRES_LIBRARY_OBSOLETE_INDEX_NAMES = (
    # 库存索引：旧 btree / 多 GIN 写放大明显，已由复合业务索引和合并 trigram 表达式索引覆盖。
    "idx_lie_library_parent",
    "ix_library_index_entries_library_id",
    "idx_lie_library_rj",
    "idx_lie_library_name",
    "idx_lie_rj_depth",
    "idx_lie_rj_scope_type_depth",
    "idx_library_index_name_trgm",
    "idx_library_index_relative_path_trgm",
    "idx_library_index_rjcode_trgm",
    "idx_library_index_parent_path_trgm",
)


_POSTGRES_TRIGRAM_INDEX_SPECS = (
    {
        "name": "idx_activity_logs_summary_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_summary_trgm ON activity_logs USING gin (COALESCE(summary, '') gin_trgm_ops)",
    },
    {
        "name": "idx_activity_logs_source_path_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_source_path_trgm ON activity_logs USING gin (COALESCE(source_path, '') gin_trgm_ops)",
    },
    {
        "name": "idx_activity_logs_rjcode_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_rjcode_trgm ON activity_logs USING gin (COALESCE(rjcode, '') gin_trgm_ops)",
    },
    {
        "name": "idx_activity_logs_task_id_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_task_id_trgm ON activity_logs USING gin (COALESCE(task_id, '') gin_trgm_ops)",
    },
    {
        "name": "idx_activity_logs_batch_id_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_batch_id_trgm ON activity_logs USING gin (COALESCE(batch_id, '') gin_trgm_ops)",
    },
    {
        "name": "idx_task_center_searchable_text_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_searchable_text_trgm ON task_center_items USING gin (searchable_text gin_trgm_ops)",
    },
    {
        "name": "idx_task_center_title_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_title_trgm ON task_center_items USING gin (title gin_trgm_ops)",
    },
    {
        "name": "idx_task_center_business_key_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_business_key_trgm ON task_center_items USING gin (business_key gin_trgm_ops)",
    },
    {
        "name": "idx_task_center_engine_task_id_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_center_engine_task_id_trgm ON task_center_items USING gin (engine_task_id gin_trgm_ops)",
    },
    {
        "name": "idx_processed_archives_filename_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_processed_archives_filename_trgm ON processed_archives USING gin (filename gin_trgm_ops)",
    },
    {
        "name": "idx_processed_archives_rjcode_trgm",
        "sql": "CREATE INDEX IF NOT EXISTS idx_processed_archives_rjcode_trgm ON processed_archives USING gin (rjcode gin_trgm_ops)",
    },
)


_POSTGRES_LIBRARY_SEARCH_TEXT_SQL = (
    "COALESCE(name, '') || ' ' || "
    "COALESCE(relative_path, '') || ' ' || "
    "COALESCE(rjcode, '') || ' ' || "
    "COALESCE(parent_path, '')"
)


_POSTGRES_LIBRARY_TRIGRAM_INDEX_SPECS = (
    {
        "name": "idx_library_index_search_text_trgm",
        "sql": (
            "CREATE INDEX IF NOT EXISTS idx_library_index_search_text_trgm "
            f"ON library_index_entries USING gin (({_POSTGRES_LIBRARY_SEARCH_TEXT_SQL}) gin_trgm_ops) "
            "WITH (fastupdate = on, gin_pending_list_limit = 65536)"
        ),
        "fragments": (
            "library_index_entries",
            "gin_trgm_ops",
            "coalesce(name",
            "relative_path",
            "rjcode",
            "parent_path",
            "fastupdate='on'",
            "gin_pending_list_limit='65536'",
        ),
    },
)


_POSTGRES_LIBRARY_TRIGRAM_INDEX_NAMES = tuple(
    str(spec["name"]) for spec in _POSTGRES_LIBRARY_TRIGRAM_INDEX_SPECS
)


_POSTGRES_LIBRARY_INDEX_TABLE_REL_OPTIONS = {
    # 首建是几十万行批量写入；日常通常只有千级 mutation。这里让统计信息在小增量后也足够新，
    # 同时把 vacuum 触发点控制在数千死元组，避免维护线程频繁打扰正常业务。
    "autovacuum_analyze_scale_factor": "0.001",
    "autovacuum_analyze_threshold": "500",
    "autovacuum_vacuum_scale_factor": "0.005",
    "autovacuum_vacuum_threshold": "1000",
}


_POSTGRES_COMPAT_INDEX_SPECS = (
    {
        "table": "activity_logs",
        "name": "idx_activity_batch_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_batch_created ON activity_logs(batch_id, created_at DESC)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_session_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_session_created ON activity_logs(session_key, created_at DESC)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_parent_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_parent_created ON activity_logs(parent_id, created_at DESC)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_task_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_task_created ON activity_logs(task_id, created_at DESC)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_rj_category_status_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_rj_category_status_created ON activity_logs(rjcode, category, status, created_at DESC)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_category_batch",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_category_batch ON activity_logs(category, batch_id)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_category_session",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_category_session ON activity_logs(category, session_key)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_status_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_status_created ON activity_logs(status, created_at)",
    },
    {
        "table": "activity_logs",
        "name": "idx_activity_category_status_created",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_category_status_created ON activity_logs(category, status, created_at)",
    },
    {
        "table": "activity_log_rollups",
        "name": "idx_activity_rollup_type_value",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_rollup_type_value ON activity_log_rollups(rollup_type, group_value)",
    },
    {
        "table": "activity_log_rollups",
        "name": "idx_activity_rollup_category_status",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_rollup_category_status ON activity_log_rollups(category, latest_status)",
    },
    {
        "table": "task_phase_metrics",
        "name": "idx_task_phase_metrics_task_phase",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_phase_metrics_task_phase ON task_phase_metrics(task_id, phase)",
    },
    {
        "table": "task_phase_metrics",
        "name": "idx_task_phase_metrics_type_phase",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_phase_metrics_type_phase ON task_phase_metrics(task_type, phase)",
    },
    {
        "table": "task_phase_metrics",
        "name": "idx_task_phase_metrics_created_at",
        "sql": "CREATE INDEX IF NOT EXISTS idx_task_phase_metrics_created_at ON task_phase_metrics(created_at)",
    },
)


def _compact_index_definition(value: Any) -> str:
    text_value = " ".join(str(value or "").lower().split())
    for marker in ("::text", "::character varying", "::bigint", "::integer"):
        text_value = text_value.replace(marker, "")
    return text_value


def _index_definition_matches(indexdef: str, fragments: tuple[str, ...]) -> bool:
    compact = _compact_index_definition(indexdef)
    return all(_compact_index_definition(fragment) in compact for fragment in fragments)


def _index_names_from_specs(specs: Iterable[Dict[str, Any]]) -> list[str]:
    return [str(spec["name"]) for spec in specs if spec.get("name")]


def _load_index_definitions(conn, names: Iterable[str]) -> Dict[str, str]:
    unique_names = sorted({str(name) for name in names if name})
    if not unique_names:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT indexname, indexdef
              FROM pg_indexes
             WHERE schemaname = current_schema()
               AND indexname = ANY(:names)
            """
        ),
        {"names": unique_names},
    ).mappings().all()
    return {str(row["indexname"]): str(row["indexdef"] or "") for row in rows}


def _load_index_states(conn, names: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    unique_names = sorted({str(name) for name in names if name})
    if not unique_names:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT c.relname AS indexname,
                   pg_get_indexdef(c.oid) AS indexdef,
                   i.indisvalid AS valid,
                   i.indisready AS ready
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_index i ON i.indexrelid = c.oid
             WHERE n.nspname = current_schema()
               AND c.relkind = 'i'
               AND c.relname = ANY(:names)
            """
        ),
        {"names": unique_names},
    ).mappings().all()
    return {
        str(row["indexname"]): {
            "indexdef": str(row["indexdef"] or ""),
            "valid": bool(row["valid"]),
            "ready": bool(row["ready"]),
        }
        for row in rows
    }


def _load_managed_index_definitions(conn) -> Dict[str, str]:
    return _load_index_definitions(conn, _index_names_from_specs(_POSTGRES_BUSINESS_INDEX_SPECS))


def _ensure_index_exists(conn, spec: Dict[str, Any], existing_definitions: Optional[Dict[str, str]] = None) -> None:
    name = str(spec["name"])
    if existing_definitions is not None and name in existing_definitions:
        return
    conn.execute(text(str(spec["sql"])))
    if existing_definitions is not None:
        existing_definitions[name] = str(spec["sql"])


def _ensure_indexes_exist(
    conn,
    specs: Iterable[Dict[str, Any]],
    existing_definitions: Optional[Dict[str, str]] = None,
) -> None:
    spec_list = [spec for spec in specs if spec.get("name")]
    if existing_definitions is None:
        existing_definitions = _load_index_definitions(conn, _index_names_from_specs(spec_list))
    for spec in spec_list:
        _ensure_index_exists(conn, spec, existing_definitions)


def _index_specs_for_table(specs: Iterable[Dict[str, Any]], table_name: str) -> list[Dict[str, Any]]:
    return [spec for spec in specs if spec.get("table") == table_name]


def _ensure_managed_index(conn, spec: Dict[str, Any], existing_definitions: Optional[Dict[str, str]] = None) -> None:
    name = str(spec["name"])
    existing = (existing_definitions or {}).get(name)
    if existing and not _index_definition_matches(str(existing), tuple(spec.get("fragments") or ())):
        conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        _db_logger.info("[数据库] 已重建 PostgreSQL 业务索引定义: %s", name)
        if existing_definitions is not None:
            existing_definitions.pop(name, None)
        existing = None
    if existing:
        return
    conn.execute(text(str(spec["sql"])))
    if existing_definitions is not None:
        existing_definitions[name] = str(spec["sql"])


def _drop_obsolete_postgres_indexes(conn, existing_definitions: Optional[Dict[str, str]] = None) -> None:
    if not _POSTGRES_OBSOLETE_INDEX_NAMES:
        return
    if existing_definitions is None:
        existing_definitions = _load_index_definitions(conn, _POSTGRES_OBSOLETE_INDEX_NAMES)
    for name in _POSTGRES_OBSOLETE_INDEX_NAMES:
        if name not in existing_definitions:
            continue
        conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        existing_definitions.pop(name, None)


def _ensure_library_index_table_reloptions(conn) -> None:
    row = conn.execute(
        text(
            """
            SELECT COALESCE(c.reloptions, ARRAY[]::text[]) AS reloptions
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = current_schema()
               AND c.relname = 'library_index_entries'
            """
        )
    ).mappings().first()
    if not row:
        return
    expected = {
        f"{name}={value}"
        for name, value in _POSTGRES_LIBRARY_INDEX_TABLE_REL_OPTIONS.items()
    }
    current = {str(item) for item in (row.get("reloptions") or [])}
    if expected <= current:
        return
    assignments = ", ".join(
        f"{name} = {value}"
        for name, value in _POSTGRES_LIBRARY_INDEX_TABLE_REL_OPTIONS.items()
    )
    conn.execute(text(f"ALTER TABLE library_index_entries SET ({assignments})"))


def _concurrent_create_index_sql(sql: str) -> str:
    prefix = "CREATE INDEX IF NOT EXISTS "
    if sql.startswith(prefix):
        return "CREATE INDEX CONCURRENTLY IF NOT EXISTS " + sql[len(prefix):]
    return sql.replace("CREATE INDEX ", "CREATE INDEX CONCURRENTLY ", 1)


_LIBRARY_INDEX_MAINTENANCE_ADVISORY_LOCK = (53901, 18004)


def configure_postgres_online_maintenance_connection(conn, *, lock_timeout_ms: int = 3000) -> bool:
    """给在线索引维护连接设置独立保护。

    业务连接统一带 statement_timeout；但几十万文件的 GIN trigram 索引首次构建可能超过
    120s。维护连接必须允许长语句，同时用短 lock_timeout 和 advisory lock 避免卡住业务。
    """
    acquired = bool(
        conn.execute(
            text("SELECT pg_try_advisory_lock(:key1, :key2)"),
            {
                "key1": _LIBRARY_INDEX_MAINTENANCE_ADVISORY_LOCK[0],
                "key2": _LIBRARY_INDEX_MAINTENANCE_ADVISORY_LOCK[1],
            },
        ).scalar()
    )
    if not acquired:
        return False
    try:
        conn.execute(text("SET statement_timeout = 0"))
        conn.execute(text(f"SET lock_timeout = '{max(100, int(lock_timeout_ms))}ms'"))
        conn.execute(text("SET application_name = 'kikoerumanager-index-maintenance'"))
        return True
    except Exception:
        release_postgres_online_maintenance_lock(conn)
        raise


def release_postgres_online_maintenance_lock(conn) -> None:
    try:
        conn.execute(
            text("SELECT pg_advisory_unlock(:key1, :key2)"),
            {
                "key1": _LIBRARY_INDEX_MAINTENANCE_ADVISORY_LOCK[0],
                "key2": _LIBRARY_INDEX_MAINTENANCE_ADVISORY_LOCK[1],
            },
        )
    finally:
        # 维护连接会把 statement_timeout 拉到 0。SQLAlchemy 连接池归还连接时只 rollback，
        # 不会还原 session 级 SET；显式恢复到应用配置值，避免普通业务借到无超时连接。
        try:
            timeout_ms = int(_DB_RUNTIME_CONFIG.get("statement_timeout_ms") or 120000)
            conn.execute(text(f"SET statement_timeout = {max(1000, timeout_ms)}"))
            conn.execute(text("RESET lock_timeout"))
            conn.execute(text("RESET application_name"))
        except Exception:
            _db_logger.debug("[数据库] 重置 PostgreSQL 维护连接参数失败", exc_info=True)


def clean_library_index_trigram_pending_list(target_engine=None, *, lock_timeout_ms: int = 500) -> Dict[str, Any]:
    """清理库存 trigram GIN pending list。

    `fastupdate=on` 对日常千级 self-mutation 友好，但全量重建/大批导入后 pending list
    会让首次模糊搜索把一大段待合并列表也扫一遍。这里只给大批路径显式调用。
    """
    cleaned: dict[str, int] = {}
    started = time.monotonic()
    db_engine = target_engine or engine
    conn = db_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_acquired = False
    try:
        lock_acquired = configure_postgres_online_maintenance_connection(
            conn,
            lock_timeout_ms=lock_timeout_ms,
        )
        if not lock_acquired:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_running",
                "cleaned": cleaned,
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        for name in _POSTGRES_LIBRARY_TRIGRAM_INDEX_NAMES:
            exists = bool(
                conn.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": name},
                ).scalar()
            )
            if not exists:
                continue
            cleaned[name] = int(
                conn.execute(
                    text("SELECT gin_clean_pending_list(:name)"),
                    {"name": name},
                ).scalar() or 0
            )
    except Exception as exc:
        _db_logger.debug("[数据库] 清理库存 trigram pending list 失败: %s", exc, exc_info=True)
        return {
            "ok": False,
            "error": str(exc),
            "cleaned": cleaned,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    finally:
        if lock_acquired:
            try:
                release_postgres_online_maintenance_lock(conn)
            except Exception:
                _db_logger.debug("[数据库] 释放库存 GIN pending 清理锁失败", exc_info=True)
        conn.close()
    return {
        "ok": True,
        "cleaned": cleaned,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def ensure_library_index_postgres_indexes_concurrently(target_engine=None) -> Dict[str, Any]:
    """在线维护库存大表索引。

    `library_index_entries` 可能有几十万到百万级文件行。这里必须使用
    CONCURRENTLY + AUTOCOMMIT，避免启动或维护时用普通 CREATE/REINDEX 阻塞业务写入。
    """
    specs = list(_POSTGRES_LIBRARY_INDEX_SPECS) + list(_POSTGRES_LIBRARY_TRIGRAM_INDEX_SPECS)
    desired_names = _index_names_from_specs(specs)
    obsolete_names = list(_POSTGRES_LIBRARY_OBSOLETE_INDEX_NAMES)
    created: list[str] = []
    recreated: list[str] = []
    dropped: list[str] = []
    started = time.monotonic()
    db_engine = target_engine or engine
    conn = db_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_acquired = False
    try:
        lock_acquired = configure_postgres_online_maintenance_connection(conn)
        if not lock_acquired:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_running",
                "created": created,
                "recreated": recreated,
                "dropped": dropped,
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        states = _load_index_states(conn, desired_names + obsolete_names)
        for spec in specs:
            name = str(spec["name"])
            state = states.get(name)
            fragments = tuple(spec.get("fragments") or ())
            drifted = bool(state) and fragments and not _index_definition_matches(str(state.get("indexdef") or ""), fragments)
            invalid = bool(state) and (not bool(state.get("valid")) or not bool(state.get("ready")))
            if drifted or invalid:
                conn.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
                states.pop(name, None)
                recreated.append(name)
                state = None
            if not state:
                conn.execute(text(_concurrent_create_index_sql(str(spec["sql"]))))
                created.append(name)
                states[name] = {"indexdef": str(spec["sql"]), "valid": True, "ready": True}

        states = _load_index_states(conn, obsolete_names)
        for name in obsolete_names:
            if name not in states:
                continue
            conn.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
            dropped.append(name)
        if created or recreated or dropped:
            conn.execute(text("ANALYZE library_index_entries"))
    finally:
        if lock_acquired:
            try:
                release_postgres_online_maintenance_lock(conn)
            except Exception:
                _db_logger.debug("[数据库] 释放库存索引维护锁失败", exc_info=True)
        conn.close()
    return {
        "ok": True,
        "created": created,
        "recreated": recreated,
        "dropped": dropped,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


@contextmanager
def suspend_library_index_secondary_indexes_for_initial_bulk_load(target_engine=None):
    """全表首建库存索引时，暂停维护可重建的二级索引。

    调用方必须只在 `library_index_entries` 业务行为空时进入。函数持有同一把
    advisory lock 到恢复完成，避免后台维护线程在二级索引暂停期间交叉重建。
    `idx_lie_library_rel` 唯一索引负责幂等约束，首建期间也必须保留。
    """
    specs = list(_POSTGRES_LIBRARY_INDEX_SPECS) + list(_POSTGRES_LIBRARY_TRIGRAM_INDEX_SPECS)
    names = _index_names_from_specs(specs)
    dropped: list[str] = []
    restored: list[str] = []
    started = time.monotonic()
    db_engine = target_engine or engine
    conn = db_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_acquired = False
    state: Dict[str, Any] = {
        "ok": True,
        "active": False,
        "skipped": False,
        "dropped": dropped,
        "restored": restored,
        "duration_ms": 0,
    }
    try:
        lock_acquired = configure_postgres_online_maintenance_connection(conn)
        if not lock_acquired:
            state.update({"skipped": True, "reason": "already_running"})
            yield state
            return
        state["active"] = True
        try:
            states = _load_index_states(conn, names)
            for name in names:
                if name not in states:
                    continue
                conn.execute(text(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"'))
                dropped.append(name)
        except Exception as exc:
            if dropped:
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                    for spec in specs:
                        conn.execute(text(_concurrent_create_index_sql(str(spec["sql"]))))
                        restored.append(str(spec["name"]))
                    conn.execute(text("ANALYZE library_index_entries"))
                except Exception:
                    _db_logger.warning("[数据库] 暂停库存二级索引失败后恢复索引也失败", exc_info=True)
            state.update({
                "active": False,
                "skipped": True,
                "reason": "drop_failed",
                "error": str(exc),
            })
            _db_logger.info("[数据库] 首建库存索引时暂停二级索引失败，改用普通写入", exc_info=True)
            yield state
            return
        try:
            yield state
        finally:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            for spec in specs:
                conn.execute(text(_concurrent_create_index_sql(str(spec["sql"]))))
                restored.append(str(spec["name"]))
            conn.execute(text("ANALYZE library_index_entries"))
    finally:
        state["duration_ms"] = int((time.monotonic() - started) * 1000)
        if lock_acquired:
            try:
                release_postgres_online_maintenance_lock(conn)
            except Exception:
                _db_logger.debug("[数据库] 释放库存二级索引首建锁失败", exc_info=True)
        conn.close()


def _library_index_maintenance_worker() -> None:
    try:
        result = ensure_library_index_postgres_indexes_concurrently()
        if result.get("created") or result.get("recreated") or result.get("dropped"):
            _db_logger.info("[数据库] 库存索引在线维护完成: %s", result)
    except Exception:
        _db_logger.warning("[数据库] 库存索引在线维护失败", exc_info=True)
    finally:
        try:
            _library_index_maintenance_lock.release()
        except RuntimeError:
            pass


def schedule_library_index_postgres_index_maintenance() -> bool:
    global _library_index_maintenance_thread
    if not _library_index_maintenance_lock.acquire(blocking=False):
        return False
    thread = threading.Thread(
        target=_library_index_maintenance_worker,
        name="library-index-postgres-index-maintenance",
        daemon=True,
    )
    _library_index_maintenance_thread = thread
    thread.start()
    return True


def check_database_health(*, full: bool = False) -> Dict[str, Any]:
    started = time.monotonic()
    result: Dict[str, Any] = {
        "ok": False,
        "check": "vacuum_analyze_probe" if full else "select_1",
        "backend": "postgresql",
        "database_url": _mask_database_url(_DATABASE_URL),
        "host": _DB_RUNTIME_CONFIG.get("host"),
        "port": _DB_RUNTIME_CONFIG.get("port"),
        "database": _DB_RUNTIME_CONFIG.get("database"),
        "pool_size": _DB_RUNTIME_CONFIG["pool_size"],
        "max_overflow": _DB_RUNTIME_CONFIG["max_overflow"],
        "statement_timeout_ms": _DB_RUNTIME_CONFIG["statement_timeout_ms"],
        "messages": [],
        "duration_ms": 0,
    }
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1")).scalar()
            result["ok"] = row == 1
            result["messages"] = ["ok"] if result["ok"] else ["SELECT 1 未返回 1"]
            result["server_version"] = str(conn.execute(text("SHOW server_version")).scalar() or "")
            result["pg_trgm_enabled"] = bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")).scalar())
            if full:
                result["database_size_bytes"] = int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
                result["database_size_human"] = _human_bytes(result["database_size_bytes"])
                result["activity_logs_size_bytes"] = _pg_table_size(conn, "activity_logs")
                result["library_index_size_bytes"] = _pg_table_size(conn, "library_index_entries")
                conn.execute(text("ANALYZE activity_logs"))
                conn.execute(text("ANALYZE library_index_entries"))
                result["messages"].append("ANALYZE activity_logs/library_index_entries ok")
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        result["messages"] = [str(exc)]
    finally:
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def _create_postgres_extensions_and_indexes(conn) -> None:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    nested = conn.begin_nested()
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
        nested.commit()
    except Exception as exc:
        nested.rollback()
        _db_logger.debug("[数据库] pg_stat_statements 扩展创建失败，慢查询 Top SQL 将不可用: %s", exc)
    tracked_index_names = (
        _index_names_from_specs(_POSTGRES_TRIGRAM_INDEX_SPECS)
        + _index_names_from_specs(_POSTGRES_BUSINESS_INDEX_SPECS)
        + list(_POSTGRES_OBSOLETE_INDEX_NAMES)
    )
    existing_definitions = _load_index_definitions(conn, tracked_index_names)
    for spec in _POSTGRES_TRIGRAM_INDEX_SPECS:
        _ensure_index_exists(conn, spec, existing_definitions)
    for spec in _POSTGRES_BUSINESS_INDEX_SPECS:
        _ensure_managed_index(conn, spec, existing_definitions)
    _drop_obsolete_postgres_indexes(conn, existing_definitions)
    _ensure_library_index_table_reloptions(conn)


def _reindex_if_exists(conn, index_name: str) -> None:
    exists = bool(conn.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": index_name}).scalar())
    if exists:
        conn.execute(text(f"REINDEX INDEX {index_name}"))


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return bool(conn.execute(
        text(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = :table_name
                 AND column_name = :column_name
            )
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar())


def _existing_columns(conn, table_name: str, column_names: Iterable[str]) -> set[str]:
    names = sorted({str(name) for name in column_names if name})
    if not names:
        return set()
    rows = conn.execute(
        text(
            """
            SELECT attname
              FROM pg_attribute
             WHERE attrelid = to_regclass(:table_name)
               AND attname = ANY(:names)
               AND attnum > 0
               AND NOT attisdropped
            """
        ),
        {"table_name": table_name, "names": names},
    ).fetchall()
    return {str(row[0]) for row in rows}


def _add_column_if_missing(
    conn,
    table_name: str,
    column_name: str,
    column_type: str,
    default_sql: Optional[str] = None,
    existing_columns: Optional[set[str]] = None,
) -> bool:
    if existing_columns is not None:
        if column_name in existing_columns:
            return False
    elif _column_exists(conn, table_name, column_name):
        return False
    default_clause = f" DEFAULT {default_sql}" if default_sql is not None else ""
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}"))
    if existing_columns is not None:
        existing_columns.add(column_name)
    _db_logger.info("[数据库] %s 新增列: %s", table_name, column_name)
    return True


def _existing_tables(conn, table_names: Iterable[str]) -> set[str]:
    names = sorted({str(name) for name in table_names if name})
    if not names:
        return set()
    rows = conn.execute(
        text(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = current_schema()
               AND c.relkind IN ('r', 'p')
               AND c.relname = ANY(:names)
            """
        ),
        {"names": names},
    ).fetchall()
    return {str(row[0]) for row in rows}


def _table_exists(conn, table_name: str) -> bool:
    return bool(conn.execute(
        text("SELECT to_regclass(:name) IS NOT NULL"),
        {"name": table_name},
    ).scalar())


def _migrate_activity_logs_projection(
    conn,
    existing_tables: Optional[set[str]] = None,
    existing_index_definitions: Optional[Dict[str, str]] = None,
) -> None:
    if existing_tables is not None:
        if "activity_logs" not in existing_tables:
            return
    elif not _table_exists(conn, "activity_logs"):
        return
    added_columns = set()
    projection_columns = (
        ("batch_id", "VARCHAR(80)"),
        ("session_key", "VARCHAR(120)"),
        ("parent_id", "VARCHAR(36)"),
    )
    existing_columns = _existing_columns(conn, "activity_logs", [name for name, _ in projection_columns])
    for column_name, column_type in projection_columns:
        if _add_column_if_missing(conn, "activity_logs", column_name, column_type, existing_columns=existing_columns):
            added_columns.add(column_name)
    _ensure_indexes_exist(
        conn,
        _index_specs_for_table(_POSTGRES_COMPAT_INDEX_SPECS, "activity_logs"),
        existing_index_definitions,
    )
    if "batch_id" in added_columns:
        conn.execute(text("""
            UPDATE activity_logs
               SET batch_id = left(COALESCE(detail ->> 'batch_id', ''), 80)
             WHERE batch_id IS NULL
               AND detail ? 'batch_id'
        """))
    if "session_key" in added_columns:
        conn.execute(text("""
            UPDATE activity_logs
               SET session_key = left(COALESCE(detail ->> 'session_key', detail ->> 'session_id', ''), 120)
             WHERE session_key IS NULL
               AND (detail ? 'session_key' OR detail ? 'session_id')
        """))


def _migrate_activity_log_daily_stats(conn, existing_tables: Optional[set[str]] = None) -> None:
    if existing_tables is not None:
        if not {"activity_log_daily_stats", "activity_logs"} <= existing_tables:
            return
    elif not _table_exists(conn, "activity_log_daily_stats") or not _table_exists(conn, "activity_logs"):
        return
    row_count = int(conn.execute(text("SELECT count(*) FROM activity_log_daily_stats")).scalar() or 0)
    if row_count > 0:
        return
    activity_total = int(conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0)
    if activity_total > 0:
        conn.execute(text("""
            INSERT INTO activity_log_daily_stats(date, category, status, count, updated_at)
            SELECT to_char(created_at, 'YYYY-MM-DD') AS date,
                   COALESCE(category, '') AS category,
                   COALESCE(status, '') AS status,
                   count(*) AS cnt,
                   CURRENT_TIMESTAMP
              FROM activity_logs
             WHERE created_at IS NOT NULL
             GROUP BY to_char(created_at, 'YYYY-MM-DD'), category, status
            ON CONFLICT(date, category, status) DO UPDATE SET
                count = EXCLUDED.count,
                updated_at = CURRENT_TIMESTAMP
        """))
        _db_logger.info("[数据库] activity_log_daily_stats 初次回填完成")


def _migrate_library_index_status_schema(conn, existing_tables: Optional[set[str]] = None) -> None:
    if existing_tables is not None:
        if "library_index_status" not in existing_tables:
            return
    elif not _table_exists(conn, "library_index_status"):
        return
    existing_columns = _existing_columns(conn, "library_index_status", ("total_size_bytes", "folder_count"))
    missing_total = "total_size_bytes" not in existing_columns
    missing_folders = "folder_count" not in existing_columns
    _add_column_if_missing(conn, "library_index_status", "total_size_bytes", "BIGINT", "0", existing_columns=existing_columns)
    _add_column_if_missing(conn, "library_index_status", "folder_count", "INTEGER", "0", existing_columns=existing_columns)
    if missing_total or missing_folders:
        conn.execute(text("""
            UPDATE library_index_status
               SET total_size_bytes = COALESCE((
                     SELECT SUM(e.size)
                       FROM library_index_entries e
                      WHERE e.library_id = library_index_status.library_id
                        AND e.entry_type = 'file'
                   ), 0),
                   folder_count = COALESCE((
                     SELECT COUNT(1)
                       FROM library_index_entries e
                      WHERE e.library_id = library_index_status.library_id
                        AND e.entry_type = 'dir'
                        AND e.relative_path != ''
                        AND COALESCE(e.parent_path, '') = ''
                   ), 0)
             WHERE status IN ('ready', 'syncing', 'error')
        """))


def _migrate_library_owned_works_schema(conn, existing_tables: Optional[set[str]] = None) -> None:
    if existing_tables is not None:
        if "library_owned_works" not in existing_tables:
            return
    elif not _table_exists(conn, "library_owned_works"):
        return
    owned_columns = (
        ("folder_size", "BIGINT", "0"),
        ("file_count", "INTEGER", "0"),
        ("owned_paths", "JSONB", "'[]'::jsonb"),
        ("has_local_subtitles", "BOOLEAN", "false"),
        ("subtitle_file_count", "INTEGER", "0"),
        ("subtitle_dir", "TEXT", None),
    )
    existing_columns = _existing_columns(conn, "library_owned_works", [name for name, _type, _default in owned_columns])
    for column_name, column_type, default_sql in owned_columns:
        _add_column_if_missing(
            conn,
            "library_owned_works",
            column_name,
            column_type,
            default_sql,
            existing_columns=existing_columns,
        )


def _migrate_library_index_entries_schema(conn, existing_tables: Optional[set[str]] = None) -> None:
    if existing_tables is not None:
        if "library_index_entries" not in existing_tables:
            return
    elif not _table_exists(conn, "library_index_entries"):
        return
    existing_columns = _existing_columns(conn, "library_index_entries", ("name_sort_key",))
    added = _add_column_if_missing(
        conn,
        "library_index_entries",
        "name_sort_key",
        "TEXT",
        "''",
        existing_columns=existing_columns,
    )
    if not added:
        stale_exists = bool(conn.execute(text("""
            SELECT 1
              FROM library_index_entries
             WHERE COALESCE(name_sort_key, '') = ''
               AND COALESCE(name, '') <> ''
             LIMIT 1
        """)).first())
        if not stale_exists:
            return

    chunk_size = 5000
    updated_total = 0
    while True:
        rows = conn.execute(
            text("""
                SELECT id, name
                  FROM library_index_entries
                 WHERE COALESCE(name_sort_key, '') = ''
                   AND COALESCE(name, '') <> ''
                 ORDER BY id
                 LIMIT :limit
            """),
            {"limit": chunk_size},
        ).mappings().all()
        if not rows:
            break
        payload = [
            {
                "id": int(row["id"]),
                "name_sort_key": library_index_name_sort_key(row["name"]),
            }
            for row in rows
        ]
        conn.execute(
            text("""
                UPDATE library_index_entries AS target
                   SET name_sort_key = payload.name_sort_key
                  FROM (
                      SELECT *
                        FROM unnest(
                            CAST(:ids AS integer[]),
                            CAST(:name_sort_keys AS text[])
                        ) AS payload(id, name_sort_key)
                  ) AS payload
                 WHERE target.id = payload.id
            """),
            {
                "ids": [item["id"] for item in payload],
                "name_sort_keys": [item["name_sort_key"] for item in payload],
            },
        )
        updated_total += len(payload)
    if updated_total:
        _db_logger.info("[数据库] library_index_entries.name_sort_key 回填完成 rows=%s", updated_total)


def _migrate_compat_schema(conn) -> None:
    existing_tables = _existing_tables(conn, (
        "processed_archives",
        "notification_templates",
        "activity_log_rollups",
        "task_phase_metrics",
        "library_index_status",
        "library_index_entries",
        "activity_logs",
        "activity_log_daily_stats",
    ))
    compat_index_specs = [
        spec
        for spec in _POSTGRES_COMPAT_INDEX_SPECS
        if str(spec.get("table") or "") in existing_tables
    ]
    compat_index_definitions = _load_index_definitions(conn, _index_names_from_specs(compat_index_specs))
    if "processed_archives" in existing_tables:
        existing_columns = _existing_columns(conn, "processed_archives", ("volume_count",))
        _add_column_if_missing(conn, "processed_archives", "volume_count", "INTEGER", "1", existing_columns=existing_columns)
    if "notification_templates" in existing_tables:
        existing_columns = _existing_columns(conn, "notification_templates", ("editor_mode", "blocks"))
        _add_column_if_missing(conn, "notification_templates", "editor_mode", "VARCHAR(20)", "'html'", existing_columns=existing_columns)
        _add_column_if_missing(conn, "notification_templates", "blocks", "JSONB", "'[]'::jsonb", existing_columns=existing_columns)
    if "activity_log_rollups" in existing_tables:
        _ensure_indexes_exist(
            conn,
            _index_specs_for_table(_POSTGRES_COMPAT_INDEX_SPECS, "activity_log_rollups"),
            compat_index_definitions,
        )
    if "task_phase_metrics" in existing_tables:
        _ensure_indexes_exist(
            conn,
            _index_specs_for_table(_POSTGRES_COMPAT_INDEX_SPECS, "task_phase_metrics"),
            compat_index_definitions,
        )
    _migrate_library_index_entries_schema(conn, existing_tables)
    _migrate_library_index_status_schema(conn, existing_tables)
    _migrate_library_owned_works_schema(conn, existing_tables)
    _migrate_activity_logs_projection(conn, existing_tables, compat_index_definitions)
    _migrate_activity_log_daily_stats(conn, existing_tables)


def init_db():
    global _init_db_done
    with _init_db_lock:
        if _init_db_done:
            _db_logger.info("[数据库] 初始化已完成，跳过重复执行")
            return
        _init_db_done = True
    _db_logger.info(
        "[数据库] 初始化 PostgreSQL: %s pool=%s+%s statement_timeout=%sms",
        _mask_database_url(_DATABASE_URL),
        _DB_RUNTIME_CONFIG["pool_size"],
        _DB_RUNTIME_CONFIG["max_overflow"],
        _DB_RUNTIME_CONFIG["statement_timeout_ms"],
    )
    if _DB_RUNTIME_CONFIG.get("startup_health_check", True):
        health = check_database_health(full=False)
        if not health.get("ok"):
            _db_logger.critical("[数据库] 启动自检失败: %s", health)
            raise RuntimeError(f"数据库自检失败: {health}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _create_postgres_extensions_and_indexes(conn)
        _migrate_compat_schema(conn)
    schedule_library_index_postgres_index_maintenance()
    _db_logger.info("[数据库] PostgreSQL 表和索引初始化完成")


def activity_logs_search_status() -> Dict[str, Any]:
    state = get_activity_logs_search_rebuild_state()
    try:
        with engine.connect() as conn:
            row_count = int(conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0)
            index_rows = conn.execute(text("""
                SELECT indexname
                  FROM pg_indexes
                 WHERE schemaname = current_schema()
                   AND tablename = 'activity_logs'
                   AND indexname LIKE 'idx_activity_logs_%_trgm'
                 ORDER BY indexname
            """)).fetchall()
            pg_trgm_enabled = bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")).scalar())
        return {
            "backend": "postgresql_pg_trgm",
            "search_enabled": pg_trgm_enabled and bool(index_rows),
            "fts_enabled": pg_trgm_enabled and bool(index_rows),
            "tokenizer": "pg_trgm",
            "trigram_supported": pg_trgm_enabled,
            "row_count": row_count,
            "fts_row_count": row_count if index_rows else 0,
            "needs_upgrade": False,
            "index_count": len(index_rows),
            "rebuild": state,
        }
    except Exception:
        _db_logger.debug("[数据库] 操作记录搜索状态检查失败", exc_info=True)
        return {
            "backend": "postgresql_pg_trgm",
            "search_enabled": False,
            "fts_enabled": False,
            "tokenizer": "pg_trgm",
            "trigram_supported": False,
            "row_count": 0,
            "fts_row_count": 0,
            "needs_upgrade": False,
            "index_count": 0,
            "rebuild": state,
        }


_SEARCH_REBUILD_LOCK = threading.Lock()
_SEARCH_REBUILD_THREAD: Optional[threading.Thread] = None
_SEARCH_REBUILD_STATE: Dict[str, Any] = {
    "running": False,
    "started_at": 0.0,
    "finished_at": 0.0,
    "copied": 0,
    "total": 0,
    "ok": None,
    "reason": "",
    "target_tokenizer": "pg_trgm",
}


def get_activity_logs_search_rebuild_state() -> Dict[str, Any]:
    with _SEARCH_REBUILD_LOCK:
        return dict(_SEARCH_REBUILD_STATE)


def _broadcast_activity_search_state(snapshot: Dict[str, Any]) -> None:
    try:
        from ..core.realtime_event_service import broadcast_event

        running = bool(snapshot.get("running"))
        total = int(snapshot.get("total") or 0)
        copied = int(snapshot.get("copied") or 0)
        ok = snapshot.get("ok")
        if running:
            status = "running"
        elif ok is True:
            status = "done"
        elif ok is False:
            status = "error"
        else:
            status = "idle"
        progress = 100 if status in {"done", "error"} else (min(99, int(copied * 100 / total)) if total else 0)
        broadcast_event({
            "type": "maintenance.search.changed",
            "reason": "activity_logs",
            "id": "activity_logs_pg_trgm",
            "domain": "maintenance",
            "status": status,
            "progress": progress,
            "current_step": "操作记录 PostgreSQL trigram 索引重建中" if running else "",
            "payload": {"kind": "activity_logs", "rebuild": dict(snapshot)},
        })
    except Exception:
        _db_logger.debug("[数据库] 广播操作记录搜索索引状态失败", exc_info=True)


def _do_reindex_activity_logs_search() -> None:
    try:
        with engine.begin() as conn:
            total = int(conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0)
        with _SEARCH_REBUILD_LOCK:
            _SEARCH_REBUILD_STATE["total"] = total
            _SEARCH_REBUILD_STATE["copied"] = 0
            snapshot = dict(_SEARCH_REBUILD_STATE)
        _broadcast_activity_search_state(snapshot)
        with engine.begin() as conn:
            _create_postgres_extensions_and_indexes(conn)
            for name in (
                "idx_activity_logs_summary_trgm",
                "idx_activity_logs_source_path_trgm",
                "idx_activity_logs_rjcode_trgm",
                "idx_activity_logs_task_id_trgm",
                "idx_activity_logs_batch_id_trgm",
            ):
                _reindex_if_exists(conn, name)
        with _SEARCH_REBUILD_LOCK:
            _SEARCH_REBUILD_STATE.update({"copied": total, "ok": True, "reason": "", "running": False, "finished_at": time.time()})
            snapshot = dict(_SEARCH_REBUILD_STATE)
        _broadcast_activity_search_state(snapshot)
    except Exception as exc:
        _db_logger.warning("[数据库] 操作记录搜索索引重建失败", exc_info=True)
        with _SEARCH_REBUILD_LOCK:
            _SEARCH_REBUILD_STATE.update({"ok": False, "reason": str(exc), "running": False, "finished_at": time.time()})
            snapshot = dict(_SEARCH_REBUILD_STATE)
        _broadcast_activity_search_state(snapshot)


def trigger_activity_logs_search_rebuild(target_tokenizer: str = "pg_trgm") -> Dict[str, Any]:
    global _SEARCH_REBUILD_THREAD
    with _SEARCH_REBUILD_LOCK:
        if _SEARCH_REBUILD_STATE["running"]:
            return {"started": False, "reason": "already_running", "state": dict(_SEARCH_REBUILD_STATE)}
        _SEARCH_REBUILD_STATE.update({
            "running": True,
            "started_at": time.time(),
            "finished_at": 0.0,
            "copied": 0,
            "total": 0,
            "ok": None,
            "reason": "",
            "target_tokenizer": "pg_trgm",
        })
        snapshot = dict(_SEARCH_REBUILD_STATE)
    _broadcast_activity_search_state(snapshot)
    thread = threading.Thread(target=_do_reindex_activity_logs_search, name="activity-logs-pg-trgm-reindex", daemon=True)
    _SEARCH_REBUILD_THREAD = thread
    thread.start()
    return {"started": True, "state": get_activity_logs_search_rebuild_state()}


# 旧导出名保留给调用层，语义已切换为 PostgreSQL trigram。
activity_logs_fts_status = activity_logs_search_status
get_activity_logs_fts_rebuild_state = get_activity_logs_search_rebuild_state
trigger_activity_logs_fts_rebuild = trigger_activity_logs_search_rebuild


def activity_logs_fts_tokenizer() -> str:
    return "pg_trgm"


def activity_logs_fts_enabled() -> bool:
    return bool(activity_logs_search_status().get("search_enabled"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_path_info():
    return _mask_database_url(_DATABASE_URL)


def get_database_url_info():
    return _mask_database_url(_DATABASE_URL)
