from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, BigInteger, JSON, Index, text, Float, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from datetime import datetime, timezone
import os
import shutil
import sqlite3
import stat
import threading
from typing import Any, Callable, Dict, Optional

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
    # sqlite3 JSON 列读出来是 str；orjson.loads 同时接收 str 与 bytes
    return orjson.loads(value)

def get_local_now():
    """获取当前本地时间（用于数据库默认值）"""
    return datetime.now()

Base = declarative_base()

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
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)
    created_at = Column(DateTime, default=get_local_now)

    def to_dict(self):
        return {
            'canonical_rjcode': self.canonical_rjcode,
            'owned_rjcodes': self.owned_rjcodes or [],
            'primary_folder_path': self.primary_folder_path,
            'library_id': self.library_id,
            'folder_count': self.folder_count,
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
    category = Column(String(40), index=True)
    action = Column(String(80))
    status = Column(String(20), index=True)
    summary = Column(Text)
    detail = Column(JSON)
    rjcode = Column(String(32), index=True)
    task_id = Column(String(36), index=True)
    source_path = Column(Text)
    created_at = Column(DateTime, default=get_local_now, index=True)
    # Phase 2：从 detail JSON 提升上来的高频查询字段，建索引后替换掉合并时 O(B·N) 扫描
    batch_id = Column(String(80), index=True)
    session_key = Column(String(120), index=True)
    parent_id = Column(String(36), index=True)

    __table_args__ = (
        Index('idx_activity_created_category', 'created_at', 'category'),
        Index('idx_activity_category_batch', 'category', 'batch_id'),
        Index('idx_activity_category_session', 'category', 'session_key'),
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

    复合主键 (date, category, status)：date 为 'YYYY-MM-DD' 字符串，
    和 `strftime('%Y-%m-%d', created_at)` 一致。
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
    rjcode = Column(String(20), index=True)
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
    download_status = Column(String(20), default='cataloged', index=True)
    match_status = Column(String(20), default='unmatched', index=True)
    verify_status = Column(String(20), default='pending', index=True)
    upload_status = Column(String(20), default='pending', index=True)
    missing_reason = Column(String(120))
    session_id = Column(String(36), index=True)
    retry_count = Column(Integer, default=0)
    last_seen_at = Column(DateTime, default=get_local_now, index=True)
    last_error = Column(Text)
    extra_metadata = Column(JSON)
    created_at = Column(DateTime, default=get_local_now)
    updated_at = Column(DateTime, default=get_local_now, onupdate=get_local_now)

    __table_args__ = (
        Index('idx_asmr_resource_unique', 'rjcode', 'source_provider', 'relative_path'),
        Index('idx_asmr_resource_status', 'download_status', 'updated_at'),
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
    rjcode = Column(String(20), index=True)
    task_id = Column(String(36), index=True)
    source_provider = Column(String(40), default='asmr.one', index=True)
    source_page = Column(String(40), default='asmr-sync')
    source_action = Column(String(80), default='enhanced_download')
    source_label = Column(Text)
    status = Column(String(20), default='planning', index=True)
    queue_priority = Column(Integer, default=100, index=True)
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
    - rjcode / name / parent_path 都建索引，覆盖 RJ 搜索、按名搜索、子目录列举
    - 目录行 size 存递归大小，避免运行时反复 os.walk
    - 与 LibrarySnapshot 不冲突：LibrarySnapshot 是业务缓存（按 RJ 号单射），
      这张表是搜索索引（按多库存 + 完整路径组织）。
    """
    __tablename__ = 'library_index_entries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(String(60), nullable=False, index=True)
    entry_type = Column(String(10), nullable=False)  # 'dir' / 'file'
    relative_path = Column(Text, nullable=False)
    absolute_path = Column(Text, nullable=False)
    name = Column(String(255), nullable=False)
    rjcode = Column(String(20))
    parent_path = Column(Text)
    size = Column(BigInteger, default=0)
    file_count = Column(Integer, default=0)
    mtime = Column(BigInteger)  # 毫秒时间戳
    depth = Column(Integer)
    indexed_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('idx_lie_library_rel', 'library_id', 'relative_path', unique=True),
        Index('idx_lie_library_rj', 'library_id', 'rjcode'),
        Index('idx_lie_library_name', 'library_id', 'name'),
        Index('idx_lie_library_parent', 'library_id', 'parent_path'),
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
            'error': self.error,
            'updated_at': int(self.updated_at or 0),
        }


# 数据库连接
def _count_password_entries(db_path):
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM password_entries")
            row = cursor.fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0

def _count_table_rows(db_path, table_name):
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            exists_row = cursor.fetchone()
            if not exists_row or int(exists_row[0] or 0) <= 0:
                return 0
            cursor.execute(f"SELECT count(*) FROM {table_name}")
            row = cursor.fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0

def _migrate_legacy_db_if_needed(target_db_path):
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..')
    )
    legacy_db_path = os.path.abspath(
        os.path.join(project_root, 'backend', 'data', 'cache.db')
    )
    target_db_path = os.path.abspath(target_db_path)

    if legacy_db_path == target_db_path or not os.path.exists(legacy_db_path):
        return

    legacy_password_count = _count_password_entries(legacy_db_path)
    target_password_count = _count_password_entries(target_db_path)
    legacy_activity_count = _count_table_rows(legacy_db_path, 'activity_logs')
    target_activity_count = _count_table_rows(target_db_path, 'activity_logs')
    legacy_task_count = _count_table_rows(legacy_db_path, 'tasks')
    target_task_count = _count_table_rows(target_db_path, 'tasks')

    legacy_score = (
        legacy_password_count * 1000000
        + legacy_activity_count * 1000
        + legacy_task_count
    )
    target_score = (
        target_password_count * 1000000
        + target_activity_count * 1000
        + target_task_count
    )

    if legacy_score <= 0 or legacy_score <= target_score:
        return

    os.makedirs(os.path.dirname(target_db_path), exist_ok=True)

    if os.path.exists(target_db_path):
        backup_path = f"{target_db_path}.pre-legacy-migration"
        if not os.path.exists(backup_path):
            shutil.copy2(target_db_path, backup_path)
            _db_logger.info(f"[数据库] 已备份空目标库到: {backup_path}")

    shutil.copy2(legacy_db_path, target_db_path)
    _db_logger.warning(
        "[数据库] 检测到旧数据库并完成迁移: %s -> %s (password_entries: %s, activity_logs: %s, tasks: %s)",
        legacy_db_path,
        target_db_path,
        legacy_password_count,
        legacy_activity_count,
        legacy_task_count,
    )

def get_db_path():
    default_data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')
    )
    data_dir = os.environ.get('DATA_PATH', default_data_dir)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, 'cache.db')
    # 转换为绝对路径
    db_path = os.path.abspath(db_path)
    _migrate_legacy_db_if_needed(db_path)
    _ensure_db_writable(db_path)
    return db_path


def _ensure_db_writable(db_path: str) -> None:
    """确保 SQLite 主库 + 同目录 -journal/-wal/-shm 副本可写。

    Windows 上常见 ReadOnly 属性被备份 / 同步软件 / shutil.copy2 复制保留下来，
    一旦置位 SQLite 整个连接会被 sqlite3 模块判定为 readonly database，
    所有 INSERT/UPDATE 都会报 `attempt to write a readonly database`。
    在引擎初始化前把只读位强制清掉，免得每次重启都要手动 attrib -R。
    """
    candidates = [db_path, f"{db_path}-journal", f"{db_path}-wal", f"{db_path}-shm"]
    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            current_mode = os.stat(path).st_mode
            if not (current_mode & stat.S_IWUSR):
                os.chmod(path, current_mode | stat.S_IWUSR | stat.S_IWGRP)
                _db_logger.warning("[数据库] 已自动清除只读位: %s", path)
            if os.name == "nt":
                try:
                    import ctypes

                    FILE_ATTRIBUTE_READONLY = 0x1
                    GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
                    SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
                    attrs = GetFileAttributesW(path)
                    if attrs != -1 and (attrs & FILE_ATTRIBUTE_READONLY):
                        SetFileAttributesW(path, attrs & ~FILE_ATTRIBUTE_READONLY)
                        _db_logger.warning("[数据库] 已自动清除 Windows ReadOnly 属性: %s", path)
                except Exception:
                    _db_logger.debug("[数据库] 清除 Windows ReadOnly 属性失败，忽略", exc_info=True)
        except Exception:
            _db_logger.warning("[数据库] 检查只读属性失败 path=%s", path, exc_info=True)

# 获取数据库路径
_db_path = get_db_path()

# 数据库连接，确保支持UTF-8
# 关键调优（特别是部署在 Synology / NAS Docker 这种慢 IO 环境时）：
#   - QueuePool + pool_size=5/max_overflow=10：避免默认 SingletonThreadPool 把所有
#     线程的查询串到一根连接上，FastAPI 多任务并发时这是主要的接口超时来源。
#   - check_same_thread=False + 30s timeout：sqlite3 driver 层先等 30s 再抛
#     `database is locked`，给 WAL 写者完成事务的时间，避免一接到锁就立刻 500。
#   - pool_pre_ping=True：连接被 NAS / 网络抖动断开后能自动重连。
engine = create_engine(
    f'sqlite:///{_db_path}',
    connect_args={
        'check_same_thread': False,
        'timeout': 30,  # 秒；sqlite3 driver 内部 busy_timeout 的初值
    },
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True,
    json_serializer=_orjson_dumps,
    json_deserializer=_orjson_loads,
    echo=False
)


# SQLite PRAGMA 调优：每个新建的物理连接都执行一次。
# - journal_mode=WAL：读写不再互斥，读者只读快照，写者另开 -wal，大幅缓解
#   `database is locked`，是这次群晖卡顿的根因修复。
# - synchronous=NORMAL：WAL 下安全，且把 fsync 次数从每次提交降为 checkpoint，
#   群晖机械盘 / btrfs 上写吞吐能翻几倍。
# - busy_timeout=30000：WAL 仍可能在 checkpoint 时短暂互斥；30s 容忍窗口够用。
# - temp_store=MEMORY / cache_size=-20000：临时表与 ~20MB 页缓存放内存，加速
#   activity_logs 这类大表的扫描 / 排序。
# - foreign_keys=ON / wal_autocheckpoint=1000：保持外键检查，控制 -wal 文件尺寸。
@event.listens_for(engine, "connect")
def _sqlite_pragma_on_connect(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-20000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()
    except Exception:
        # PRAGMA 设置失败不应阻断连接建立；下游真有冲突会通过 busy_timeout 兜底。
        try:
            cursor.close()
        except Exception:
            pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_init_db_lock = threading.RLock()
_init_db_done = False


def _repair_orphan_sqlite_indexes() -> None:
    """清理 sqlite_master 里指向不存在表的孤儿索引。

    历史上如果 DB 文件被外部工具改过、或者上一次升级在 DROP TABLE 之间崩掉，
    会留下 "有索引、没表" 的孤儿条目。SQLite 在 schema 解析阶段就会抛
    `malformed database schema (<index>) - no such table: main.<table>`，
    连无关的 `PRAGMA table_info(...)` 都会过不去，直接把 init_db 卡死。
    这里在 create_all 之前用 writable_schema 把这些孤儿索引删掉。
    """
    try:
        import sqlite3
        # 直接用 sqlite3 驱动，避开 SQLAlchemy 的 schema 反射路径。
        conn = sqlite3.connect(_db_path, timeout=30)
        try:
            cur = conn.cursor()
            tables = {
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = cur.execute(
                "SELECT name, tbl_name FROM sqlite_master "
                "WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
            orphans = [name for (name, tbl) in indexes if tbl not in tables]
            if not orphans:
                return
            _db_logger.warning(
                f"[数据库] 检测到孤儿索引，将清理：{orphans}"
            )
            cur.execute("PRAGMA writable_schema=ON")
            for name in orphans:
                cur.execute(
                    "DELETE FROM sqlite_master WHERE type='index' AND name=?",
                    (name,),
                )
            cur.execute("PRAGMA writable_schema=OFF")
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        # 修复失败不应阻断启动，让后续 create_all 自己抛真正错误。
        _db_logger.warning(f"[数据库] 孤儿索引修复跳过：{exc}")


def init_db():
    """初始化数据库"""
    global _init_db_done
    with _init_db_lock:
        if _init_db_done:
            _db_logger.info("[数据库] 初始化已完成，跳过重复执行")
            return
        _init_db_done = True
    _db_logger.info(f"[数据库] 初始化数据库，路径: {_db_path}")
    _repair_orphan_sqlite_indexes()
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(work_metadata)"))
        work_metadata_columns = {row[1] for row in result.fetchall()}
        work_metadata_missing_columns = []
        if result.returns_rows:
            if 'price_text' not in work_metadata_columns:
                work_metadata_missing_columns.append(("price_text", "VARCHAR(80)", "NULL"))
            if 'is_bonus_work' not in work_metadata_columns:
                work_metadata_missing_columns.append(("is_bonus_work", "BOOLEAN", "0"))
            if 'has_bonus' not in work_metadata_columns:
                work_metadata_missing_columns.append(("has_bonus", "BOOLEAN", "0"))
            # bonus_info_checked_at：nullable，不能给默认值。NULL 表示存量条目从未走过 bonus 判定，
            # build_circle_completion_view 会按它做一次性懒迁移。给非 NULL 默认值会让"老条目"
            # 直接被当成已检查过，bonus_work=False 永远卡死。
            if 'bonus_info_checked_at' not in work_metadata_columns:
                work_metadata_missing_columns.append(("bonus_info_checked_at", "DATETIME", None))
        for column_name, column_type, default_value in work_metadata_missing_columns:
            if default_value is None:
                conn.execute(
                    text(
                        f"ALTER TABLE work_metadata ADD COLUMN {column_name} {column_type}"
                    )
                )
            else:
                conn.execute(
                    text(
                        f"ALTER TABLE work_metadata ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                    )
                )
        result = conn.execute(text("PRAGMA table_info(conflict_works)"))
        existing_columns = {row[1] for row in result.fetchall()}
        missing_columns = []
        if 'linked_works_info' not in existing_columns:
            missing_columns.append(("linked_works_info", "JSON", "'[]'"))
        if 'analysis_info' not in existing_columns:
            missing_columns.append(("analysis_info", "JSON", "'{}'"))
        if 'related_rjcodes' not in existing_columns:
            missing_columns.append(("related_rjcodes", "JSON", "'[]'"))
        for column_name, column_type, default_value in missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE conflict_works ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )
        result = conn.execute(text("PRAGMA table_info(asmr_resource_records)"))
        asmr_columns = {row[1] for row in result.fetchall()}
        asmr_missing_columns = []
        if result.returns_rows:
            if 'work_rjcode' not in asmr_columns:
                asmr_missing_columns.append(("work_rjcode", "VARCHAR(20)", "''"))
            if 'match_status' not in asmr_columns:
                asmr_missing_columns.append(("match_status", "VARCHAR(20)", "'unmatched'"))
            if 'verify_status' not in asmr_columns:
                asmr_missing_columns.append(("verify_status", "VARCHAR(20)", "'pending'"))
            if 'upload_status' not in asmr_columns:
                asmr_missing_columns.append(("upload_status", "VARCHAR(20)", "'pending'"))
            if 'missing_reason' not in asmr_columns:
                asmr_missing_columns.append(("missing_reason", "TEXT", "NULL"))
            if 'session_id' not in asmr_columns:
                asmr_missing_columns.append(("session_id", "VARCHAR(36)", "NULL"))
            if 'retry_count' not in asmr_columns:
                asmr_missing_columns.append(("retry_count", "INTEGER", "0"))
            if 'last_seen_at' not in asmr_columns:
                asmr_missing_columns.append(("last_seen_at", "DATETIME", "NULL"))
        for column_name, column_type, default_value in asmr_missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE asmr_resource_records ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )
        result = conn.execute(text("PRAGMA table_info(circle_works)"))
        circle_work_columns = {row[1] for row in result.fetchall()}
        circle_work_missing_columns = []
        if result.returns_rows:
            if 'asmr_available_rjcode' not in circle_work_columns:
                circle_work_missing_columns.append(("asmr_available_rjcode", "VARCHAR(20)", "NULL"))
            if 'kikoeru_found_rjcodes' not in circle_work_columns:
                circle_work_missing_columns.append(("kikoeru_found_rjcodes", "JSON", "'[]'"))
            if 'kikoeru_subtitle_rjcodes' not in circle_work_columns:
                circle_work_missing_columns.append(("kikoeru_subtitle_rjcodes", "JSON", "'[]'"))
            if 'image_url' not in circle_work_columns:
                circle_work_missing_columns.append(("image_url", "VARCHAR(500)", "NULL"))
            if 'price_text' not in circle_work_columns:
                circle_work_missing_columns.append(("price_text", "VARCHAR(80)", "NULL"))
            if 'is_bonus_work' not in circle_work_columns:
                circle_work_missing_columns.append(("is_bonus_work", "BOOLEAN", "0"))
            if 'has_bonus' not in circle_work_columns:
                circle_work_missing_columns.append(("has_bonus", "BOOLEAN", "0"))
            if 'source_tags' not in circle_work_columns:
                circle_work_missing_columns.append(("source_tags", "JSON", "'[]'"))
            if 'email_watcher_first_seen_at' not in circle_work_columns:
                circle_work_missing_columns.append(("email_watcher_first_seen_at", "DATETIME", "NULL"))
        for column_name, column_type, default_value in circle_work_missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE circle_works ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )
        # 为新增的 email_watcher_first_seen_at 创建索引（IF NOT EXISTS 兼容多次启动）
        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_circle_works_email_watcher_first_seen_at "
                    "ON circle_works(email_watcher_first_seen_at)"
                )
            )
        except Exception:
            _db_logger.warning("[数据库] circle_works.email_watcher_first_seen_at 索引创建失败", exc_info=True)
        result = conn.execute(text("PRAGMA table_info(asmr_download_sessions)"))
        session_columns = {row[1] for row in result.fetchall()}
        session_missing_columns = []
        if result.returns_rows:
            if 'local_download_ready' not in session_columns:
                session_missing_columns.append(("local_download_ready", "BOOLEAN", "0"))
            if 'local_download_root' not in session_columns:
                session_missing_columns.append(("local_download_root", "TEXT", "NULL"))
            if 'local_downloaded_count' not in session_columns:
                session_missing_columns.append(("local_downloaded_count", "INTEGER", "0"))
        for column_name, column_type, default_value in session_missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE asmr_download_sessions ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )

        result = conn.execute(text("PRAGMA table_info(notification_templates)"))
        template_columns = {row[1] for row in result.fetchall()}
        template_missing_columns = []
        if result.returns_rows:
            if 'editor_mode' not in template_columns:
                template_missing_columns.append(("editor_mode", "VARCHAR(20)", "'html'"))
            if 'blocks' not in template_columns:
                template_missing_columns.append(("blocks", "JSON", "'[]'"))
        for column_name, column_type, default_value in template_missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE notification_templates ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )
            _db_logger.info(f"[数据库] notification_templates 新增列: {column_name}")

        # === Phase 2: activity_logs 迁移 ===
        _migrate_activity_logs_phase2(conn)

        # === 库存索引 FTS5：只确保结构存在，老数据回填走后台线程 ===
        try:
            from ..core.library_index.fts import ensure_library_index_fts

            ensure_library_index_fts(conn)
        except Exception:
            _db_logger.warning("[数据库] library_index_entries_fts 初始化失败（非致命）", exc_info=True)

        # === Phase 4A: activity_log_daily_stats 初次回填 ===
        _migrate_activity_log_daily_stats(conn)

    _db_logger.info(f"[数据库] 表创建完成")


def _migrate_activity_log_daily_stats(conn) -> None:
    """Phase 4A 日聚合表迁移：
    - Base.metadata.create_all 已负责建表
    - 若聚合表为空，一次性从 activity_logs GROUP BY 回填历史数据
    - 之后由 ActivityLogWriter 在批量 flush 后增量维护
    """
    try:
        row_count = conn.execute(text("SELECT count(*) FROM activity_log_daily_stats")).scalar() or 0
        activity_total = conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0
        if row_count == 0 and activity_total > 0:
            conn.execute(text(
                """
                INSERT INTO activity_log_daily_stats(date, category, status, count, updated_at)
                SELECT
                    strftime('%Y-%m-%d', created_at) AS date,
                    COALESCE(category, '') AS category,
                    COALESCE(status, '') AS status,
                    count(*) AS cnt,
                    CURRENT_TIMESTAMP
                  FROM activity_logs
                 WHERE created_at IS NOT NULL
                 GROUP BY strftime('%Y-%m-%d', created_at), category, status
                """
            ))
            _db_logger.info("[数据库] activity_log_daily_stats 初次回填完成")
        try:
            conn.commit()
        except Exception:
            pass
    except Exception:
        _db_logger.warning("[数据库] activity_log_daily_stats 迁移/回填失败（非致命）", exc_info=True)


def _migrate_activity_logs_phase2(conn) -> None:
    """Phase 2 审计表迁移：
    - 新增 batch_id / session_key / parent_id 三列（带索引）
    - 用 json_extract 一次性 SQL 回填老数据（无 Python 循环）
    - 创建 FTS5 虚表 + 触发器；不支持 FTS5 的极少数构建上降级为无 FTS
    """
    activity_info = conn.execute(text("PRAGMA table_info(activity_logs)"))
    existing_cols = {row[1] for row in activity_info.fetchall()}
    missing_cols = []
    if 'batch_id' not in existing_cols:
        missing_cols.append(("batch_id", "VARCHAR(80)"))
    if 'session_key' not in existing_cols:
        missing_cols.append(("session_key", "VARCHAR(120)"))
    if 'parent_id' not in existing_cols:
        missing_cols.append(("parent_id", "VARCHAR(36)"))
    for column_name, column_type in missing_cols:
        try:
            conn.execute(text(f"ALTER TABLE activity_logs ADD COLUMN {column_name} {column_type}"))
            _db_logger.info(f"[数据库] activity_logs 新增列: {column_name}")
        except Exception:
            _db_logger.warning(f"[数据库] activity_logs 新增列失败: {column_name}", exc_info=True)

    # 索引（CREATE INDEX IF NOT EXISTS 是 SQLite 原生支持的）
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_activity_logs_batch_id ON activity_logs(batch_id)",
        "CREATE INDEX IF NOT EXISTS ix_activity_logs_session_key ON activity_logs(session_key)",
        "CREATE INDEX IF NOT EXISTS ix_activity_logs_parent_id ON activity_logs(parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_activity_category_batch ON activity_logs(category, batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_activity_category_session ON activity_logs(category, session_key)",
    ):
        try:
            conn.execute(text(index_sql))
        except Exception:
            _db_logger.debug(f"[数据库] 建索引失败: {index_sql}", exc_info=True)

    # 一次性回填：从 detail JSON 提升到新列；纯 SQL，大表也快。
    try:
        conn.execute(text(
            """
            UPDATE activity_logs
               SET batch_id = substr(COALESCE(json_extract(detail, '$.batch_id'), ''), 1, 80)
             WHERE batch_id IS NULL
               AND json_extract(detail, '$.batch_id') IS NOT NULL
            """
        ))
    except Exception:
        _db_logger.warning("[数据库] activity_logs.batch_id 回填失败（非致命）", exc_info=True)
    try:
        conn.execute(text(
            """
            UPDATE activity_logs
               SET session_key = substr(COALESCE(
                       json_extract(detail, '$.session_key'),
                       json_extract(detail, '$.session_id')
                   ), 1, 120)
             WHERE session_key IS NULL
               AND (
                   json_extract(detail, '$.session_key') IS NOT NULL
                OR json_extract(detail, '$.session_id') IS NOT NULL
               )
            """
        ))
    except Exception:
        _db_logger.warning("[数据库] activity_logs.session_key 回填失败（非致命）", exc_info=True)

    # === FTS5 虚表 + 触发器 ===
    # 启动只「确保表存在」，不强制重建：如果当前表用的是 unicode61 而 SQLite 支持
    # trigram，留给用户在设置页手动点「升级搜索引擎」走后台异步重建，避免大表启动卡顿。
    fts_available, _ = _ensure_activity_logs_fts(conn)

    # SQLAlchemy 2.0 下 engine.connect() 不会自动提交 DML/DQL 事务，
    # 这里的 UPDATE / INSERT SELECT 需要显式 commit 才会持久化。
    # DDL (ALTER / CREATE INDEX / CREATE VIRTUAL TABLE / CREATE TRIGGER) 在 SQLite 上
    # 会触发隐式提交，可以不加。为保险把两类都一起 flush。
    try:
        conn.commit()
    except Exception:
        # 某些连接实现可能没有 commit()（例如已经自动提交的场景），忽略即可
        _db_logger.debug("[数据库] activity_logs 迁移 commit 非必要", exc_info=True)


def activity_logs_fts_enabled() -> bool:
    """运行时查询当前 SQLite 是否加载了 FTS5 虚表（供查询层决定是否走 FTS）。"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_logs_fts'"
            )).fetchone()
            return row is not None
    except Exception:
        return False


# ==================== FTS5 tokenizer 检测 / 重建（运行时） ====================
#
# 设计要点：
#   1. 启动同步路径只调 `_ensure_activity_logs_fts`，存在则尽量不动它，避免对几十万行
#      表的反复 INSERT；只有「连表都不存在」才会现场创建。
#   2. trigram tokenizer（SQLite 3.34+）对中文子串搜索质量是革命性提升；老库用的
#      unicode61 把连续 CJK 字符合成一个超长 token，对中文搜索 phrase match 几乎永远
#      命中 0 行。我们把 trigram 升级做成「设置页一键迁移」+ 后台线程跑，不阻塞启动。
#   3. 触发器写入路径无论 tokenizer 是哪个都一样工作（只需要表名一致），重建索引时
#      表名保持 `activity_logs_fts`，触发器无需改写。

_FTS_TABLE_NAME = "activity_logs_fts"
_FTS_PREFERRED_TOKENIZE = "trigram"
_FTS_FALLBACK_TOKENIZE = "unicode61 remove_diacritics 2"


def _detect_trigram_supported(conn) -> bool:
    """探测当前 SQLite 是否支持 fts5 + trigram tokenizer（3.34+）。

    用临时表试创建一次，能成功就支持。失败时回滚不留垃圾。
    """
    try:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_trigram_probe USING fts5(x, tokenize='trigram')"
        ))
        try:
            conn.execute(text("DROP TABLE IF EXISTS _fts_trigram_probe"))
        except Exception:
            pass
        return True
    except Exception:
        return False


def _detect_fts5_supported(conn) -> bool:
    """探测当前 SQLite 是否支持 fts5。"""
    try:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)"
        ))
        try:
            conn.execute(text("DROP TABLE IF EXISTS _fts5_probe"))
        except Exception:
            pass
        return True
    except Exception:
        return False


def _read_fts_tokenizer(conn) -> str:
    """从 sqlite_master 里读出 activity_logs_fts 的 tokenizer 字符串。

    返回值示例：'unicode61 remove_diacritics 2' / 'trigram' / ''（不存在或解析失败）
    """
    try:
        row = conn.execute(text(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{_FTS_TABLE_NAME}'"
        )).fetchone()
        if not row or not row[0]:
            return ""
        sql_text = str(row[0])
        # CREATE VIRTUAL TABLE ... USING fts5(... tokenize='xxx')
        lower = sql_text.lower()
        idx = lower.find("tokenize")
        if idx < 0:
            # 没显式指定 tokenize，老的可能默认 simple
            return "simple"
        # 提取 tokenize=' ... ' 中间内容
        rest = sql_text[idx:]
        for quote in ("'", "\""):
            q1 = rest.find(quote)
            if q1 < 0:
                continue
            q2 = rest.find(quote, q1 + 1)
            if q2 < 0:
                continue
            return rest[q1 + 1:q2].strip().lower()
        return ""
    except Exception:
        return ""


def _create_fts_triggers(conn, table_name: str = _FTS_TABLE_NAME) -> None:
    """创建 / 替换 INSERT/UPDATE/DELETE 触发器。"""
    for trigger_sql in (
        f"""
        CREATE TRIGGER IF NOT EXISTS activity_logs_fts_ai
        AFTER INSERT ON activity_logs BEGIN
          INSERT INTO {table_name}(id, summary, source_path, rjcode, task_id, batch_id)
          VALUES (
            NEW.id,
            COALESCE(NEW.summary, ''),
            COALESCE(NEW.source_path, ''),
            COALESCE(NEW.rjcode, ''),
            COALESCE(NEW.task_id, ''),
            COALESCE(NEW.batch_id, '')
          );
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS activity_logs_fts_ad
        AFTER DELETE ON activity_logs BEGIN
          DELETE FROM {table_name} WHERE id = OLD.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS activity_logs_fts_au
        AFTER UPDATE ON activity_logs BEGIN
          DELETE FROM {table_name} WHERE id = OLD.id;
          INSERT INTO {table_name}(id, summary, source_path, rjcode, task_id, batch_id)
          VALUES (
            NEW.id,
            COALESCE(NEW.summary, ''),
            COALESCE(NEW.source_path, ''),
            COALESCE(NEW.rjcode, ''),
            COALESCE(NEW.task_id, ''),
            COALESCE(NEW.batch_id, '')
          );
        END
        """,
    ):
        try:
            conn.execute(text(trigger_sql))
        except Exception:
            _db_logger.warning("[数据库] 创建 activity_logs_fts 触发器失败", exc_info=True)


def _drop_fts_triggers(conn) -> None:
    for name in ("activity_logs_fts_ai", "activity_logs_fts_ad", "activity_logs_fts_au"):
        try:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        except Exception:
            _db_logger.debug(f"[数据库] 删除触发器失败 {name}", exc_info=True)


def _ensure_activity_logs_fts(conn) -> tuple[bool, str]:
    """启动时确保 FTS 表存在；存在就别动它。

    Returns
    -------
    (fts_available, tokenizer)
        fts_available: 当前 SQLite 是否能用 FTS5
        tokenizer: 当前表使用的 tokenizer 字符串（空 = 没有表）
    """
    if not _detect_fts5_supported(conn):
        _db_logger.warning("[数据库] 当前 SQLite 不支持 FTS5，将回退为 LIKE 搜索")
        return False, ""

    existing = _read_fts_tokenizer(conn)
    if existing:
        # 表已存在：保持触发器最新（可能是早期版本没建全）
        _create_fts_triggers(conn)
        # 容错：如果 FTS 表为空但主表非空（迁移异常 / 手动 truncate），现场补一次
        try:
            fts_count = conn.execute(text(f"SELECT count(*) FROM {_FTS_TABLE_NAME}")).scalar() or 0
            log_count = conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0
            if fts_count == 0 and log_count > 0:
                _db_logger.info("[数据库] FTS 表为空但主表有 %d 行，启动时补回填", log_count)
                conn.execute(text(
                    f"""
                    INSERT INTO {_FTS_TABLE_NAME}(id, summary, source_path, rjcode, task_id, batch_id)
                    SELECT id,
                           COALESCE(summary, ''),
                           COALESCE(source_path, ''),
                           COALESCE(rjcode, ''),
                           COALESCE(task_id, ''),
                           COALESCE(batch_id, '')
                      FROM activity_logs
                    """
                ))
        except Exception:
            _db_logger.warning("[数据库] FTS 启动回填检查失败（非致命）", exc_info=True)
        return True, existing

    # 表不存在 → 现场创建：优先 trigram，不支持就 unicode61
    use_trigram = _detect_trigram_supported(conn)
    tokenize = _FTS_PREFERRED_TOKENIZE if use_trigram else _FTS_FALLBACK_TOKENIZE
    try:
        conn.execute(text(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE_NAME} USING fts5(
                id UNINDEXED,
                summary,
                source_path,
                rjcode,
                task_id,
                batch_id,
                tokenize='{tokenize}'
            )
            """
        ))
    except Exception:
        _db_logger.warning("[数据库] 创建 activity_logs_fts 失败", exc_info=True)
        return True, ""

    # 首次回填
    try:
        conn.execute(text(
            f"""
            INSERT INTO {_FTS_TABLE_NAME}(id, summary, source_path, rjcode, task_id, batch_id)
            SELECT id,
                   COALESCE(summary, ''),
                   COALESCE(source_path, ''),
                   COALESCE(rjcode, ''),
                   COALESCE(task_id, ''),
                   COALESCE(batch_id, '')
              FROM activity_logs
            """
        ))
        _db_logger.info(f"[数据库] activity_logs_fts 初次创建完成，tokenizer={tokenize}")
    except Exception:
        _db_logger.warning("[数据库] activity_logs_fts 初次回填失败（非致命）", exc_info=True)

    _create_fts_triggers(conn)
    return True, tokenize


def activity_logs_fts_tokenizer() -> str:
    """运行时查询当前 FTS 表使用的 tokenizer，例如 'trigram' / 'unicode61 remove_diacritics 2'。

    没建表 / 不支持 FTS5 时返回空字符串。
    """
    try:
        with engine.connect() as conn:
            return _read_fts_tokenizer(conn)
    except Exception:
        return ""


def activity_logs_fts_status() -> Dict[str, Any]:
    """汇总当前搜索引擎状态，给前端「搜索引擎升级」面板用。"""
    info: Dict[str, Any] = {
        "fts_enabled": False,
        "tokenizer": "",
        "trigram_supported": False,
        "row_count": 0,
        "fts_row_count": 0,
        "needs_upgrade": False,
    }
    try:
        with engine.connect() as conn:
            info["fts_enabled"] = bool(
                conn.execute(text(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{_FTS_TABLE_NAME}'"
                )).fetchone()
            )
            info["tokenizer"] = _read_fts_tokenizer(conn)
            info["trigram_supported"] = _detect_trigram_supported(conn)
            try:
                info["row_count"] = int(conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0)
            except Exception:
                info["row_count"] = 0
            if info["fts_enabled"]:
                try:
                    info["fts_row_count"] = int(
                        conn.execute(text(f"SELECT count(*) FROM {_FTS_TABLE_NAME}")).scalar() or 0
                    )
                except Exception:
                    info["fts_row_count"] = 0
    except Exception:
        _db_logger.debug("[数据库] activity_logs_fts_status 检查失败", exc_info=True)
    info["needs_upgrade"] = bool(
        info["fts_enabled"]
        and info["trigram_supported"]
        and info["tokenizer"] != _FTS_PREFERRED_TOKENIZE
    )
    return info


def rebuild_activity_logs_fts(*, target_tokenizer: str = _FTS_PREFERRED_TOKENIZE,
                               progress_cb: Optional[Callable[[int, int], None]] = None,
                               batch_size: int = 5000) -> Dict[str, Any]:
    """重建 FTS5 索引切换 tokenizer。同步执行，调用方负责放后台线程。

    流程：
      1. 校验目标 tokenizer 是否被当前 SQLite 支持
      2. 创建临时表 activity_logs_fts_new（带新 tokenizer）
      3. 分批 INSERT FROM activity_logs（避免单事务过大）
      4. DROP 旧表 / RENAME 新表 / 重建触发器
    """
    target = (target_tokenizer or "").strip().lower() or _FTS_PREFERRED_TOKENIZE
    new_table = f"{_FTS_TABLE_NAME}_new"

    with engine.begin() as conn:
        if not _detect_fts5_supported(conn):
            return {"ok": False, "reason": "fts5_not_supported"}
        if target == _FTS_PREFERRED_TOKENIZE and not _detect_trigram_supported(conn):
            return {"ok": False, "reason": "trigram_not_supported"}
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {new_table}"))
        except Exception:
            pass
        try:
            conn.execute(text(
                f"""
                CREATE VIRTUAL TABLE {new_table} USING fts5(
                    id UNINDEXED,
                    summary,
                    source_path,
                    rjcode,
                    task_id,
                    batch_id,
                    tokenize='{target}'
                )
                """
            ))
        except Exception as exc:
            _db_logger.warning("[数据库] 创建新 FTS 表失败", exc_info=True)
            return {"ok": False, "reason": f"create_new_table_failed: {exc}"}

        total = int(conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0)
        copied = 0
        last_id: Optional[str] = None
        while True:
            if last_id is None:
                rows = conn.execute(text(
                    """
                    SELECT id, summary, source_path, rjcode, task_id, batch_id
                      FROM activity_logs
                     ORDER BY id
                     LIMIT :n
                    """
                ), {"n": batch_size}).fetchall()
            else:
                rows = conn.execute(text(
                    """
                    SELECT id, summary, source_path, rjcode, task_id, batch_id
                      FROM activity_logs
                     WHERE id > :last
                     ORDER BY id
                     LIMIT :n
                    """
                ), {"last": last_id, "n": batch_size}).fetchall()
            if not rows:
                break
            payload = [
                {
                    "id": r[0],
                    "summary": (r[1] or ""),
                    "source_path": (r[2] or ""),
                    "rjcode": (r[3] or ""),
                    "task_id": (r[4] or ""),
                    "batch_id": (r[5] or ""),
                }
                for r in rows
            ]
            conn.execute(
                text(
                    f"""
                    INSERT INTO {new_table}(id, summary, source_path, rjcode, task_id, batch_id)
                    VALUES (:id, :summary, :source_path, :rjcode, :task_id, :batch_id)
                    """
                ),
                payload,
            )
            copied += len(payload)
            last_id = rows[-1][0]
            if progress_cb is not None:
                try:
                    progress_cb(copied, total)
                except Exception:
                    pass
            if len(rows) < batch_size:
                break

        # 切换：先 DROP 触发器和旧表，再 rename 新表，再重建触发器
        _drop_fts_triggers(conn)
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {_FTS_TABLE_NAME}"))
        except Exception:
            _db_logger.warning("[数据库] 删除旧 FTS 表失败", exc_info=True)
        try:
            conn.execute(text(f"ALTER TABLE {new_table} RENAME TO {_FTS_TABLE_NAME}"))
        except Exception as exc:
            _db_logger.warning("[数据库] 重命名 FTS 新表失败", exc_info=True)
            return {"ok": False, "reason": f"rename_failed: {exc}"}
        _create_fts_triggers(conn)

    return {"ok": True, "tokenizer": target, "copied": copied, "total": total}


# ==================== FTS5 重建后台调度 ====================
#
# 设置页 / 自动升级提示触发的「重建搜索引擎索引」走这里。
# 单例后台线程，互斥执行，对外暴露状态字典供前端轮询进度。

import threading as _fts_threading

_FTS_REBUILD_STATE: Dict[str, Any] = {
    "running": False,
    "started_at": 0.0,
    "finished_at": 0.0,
    "target_tokenizer": "",
    "copied": 0,
    "total": 0,
    "ok": None,
    "reason": "",
}
_FTS_REBUILD_LOCK = _fts_threading.Lock()
_FTS_REBUILD_THREAD: Optional[_fts_threading.Thread] = None


def get_activity_logs_fts_rebuild_state() -> Dict[str, Any]:
    """快照当前重建状态（线程安全）。"""
    with _FTS_REBUILD_LOCK:
        return dict(_FTS_REBUILD_STATE)


def _do_rebuild_activity_logs_fts(target: str) -> None:
    def _progress(copied: int, total: int) -> None:
        with _FTS_REBUILD_LOCK:
            _FTS_REBUILD_STATE["copied"] = int(copied)
            _FTS_REBUILD_STATE["total"] = int(total)

    try:
        result = rebuild_activity_logs_fts(target_tokenizer=target, progress_cb=_progress)
        with _FTS_REBUILD_LOCK:
            _FTS_REBUILD_STATE["ok"] = bool(result.get("ok"))
            _FTS_REBUILD_STATE["reason"] = str(result.get("reason") or "")
            if result.get("total") is not None:
                _FTS_REBUILD_STATE["total"] = int(result.get("total") or 0)
            if result.get("copied") is not None:
                _FTS_REBUILD_STATE["copied"] = int(result.get("copied") or 0)
    except Exception as exc:
        _db_logger.warning("[数据库] FTS 重建失败", exc_info=True)
        with _FTS_REBUILD_LOCK:
            _FTS_REBUILD_STATE["ok"] = False
            _FTS_REBUILD_STATE["reason"] = f"exception: {exc}"
    finally:
        import time as _time
        with _FTS_REBUILD_LOCK:
            _FTS_REBUILD_STATE["running"] = False
            _FTS_REBUILD_STATE["finished_at"] = _time.time()


def trigger_activity_logs_fts_rebuild(target_tokenizer: str = _FTS_PREFERRED_TOKENIZE) -> Dict[str, Any]:
    """触发后台重建。已在跑就直接返回当前状态。"""
    import time as _time
    global _FTS_REBUILD_THREAD
    target = (target_tokenizer or "").strip().lower() or _FTS_PREFERRED_TOKENIZE
    with _FTS_REBUILD_LOCK:
        if _FTS_REBUILD_STATE["running"]:
            return {"started": False, "reason": "already_running", "state": dict(_FTS_REBUILD_STATE)}
        _FTS_REBUILD_STATE.update({
            "running": True,
            "started_at": _time.time(),
            "finished_at": 0.0,
            "target_tokenizer": target,
            "copied": 0,
            "total": 0,
            "ok": None,
            "reason": "",
        })
    thread = _fts_threading.Thread(
        target=_do_rebuild_activity_logs_fts,
        args=(target,),
        name="activity-logs-fts-rebuild",
        daemon=True,
    )
    _FTS_REBUILD_THREAD = thread
    thread.start()
    return {"started": True, "state": get_activity_logs_fts_rebuild_state()}


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_path_info():
    """获取数据库路径信息"""
    return _db_path
