from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, BigInteger, JSON, Index, text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import os
import shutil
import sqlite3
import stat

import orjson

# 自定义 JSON 序列化/反序列化钩子：
# SQLAlchemy 默认的 JSON 列类型会在物化 ORM 对象时对每行调用 stdlib json.loads，
# 对 activity_logs 这种 detail 较大的表 (~148μs/row) 在 5000 行窗口下能吃掉 ~700ms。
# orjson 实测比 stdlib json 快 3~5×，换上去后 list / children 接口的 JSON 反序列化
# 开销直接降到可忽略水平。
def _orjson_dumps(obj) -> str:
    # SA json_serializer 约定返回 str；orjson 返回 bytes，这里再 decode 一次
    return orjson.dumps(obj, default=str).decode('utf-8')


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
    asmr_one_cached_at = Column(DateTime)
    dlsite_cached_at = Column(DateTime)
    source_tags = Column(JSON, default=list)  # 来源标签，如 ["email_watcher"]，用于"新作"标识
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
            'asmr_one_cached_at': self.asmr_one_cached_at.isoformat() if self.asmr_one_cached_at else None,
            'dlsite_cached_at': self.dlsite_cached_at.isoformat() if self.dlsite_cached_at else None,
            'source_tags': self.source_tags or [],
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
        return {
            'id': self.id,
            'original_path': self.original_path,
            'current_path': self.current_path,
            'filename': self.filename,
            'rjcode': self.rjcode,
            'file_size': self.file_size,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
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
engine = create_engine(
    f'sqlite:///{_db_path}',
    connect_args={
        'check_same_thread': False,
    },
    json_serializer=_orjson_dumps,
    json_deserializer=_orjson_loads,
    echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """初始化数据库"""
    _db_logger.info(f"[数据库] 初始化数据库，路径: {_db_path}")
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
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
        for column_name, column_type, default_value in circle_work_missing_columns:
            conn.execute(
                text(
                    f"ALTER TABLE circle_works ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                )
            )
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

        # === Phase 2: activity_logs 迁移 ===
        _migrate_activity_logs_phase2(conn)

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
    fts_available = True
    try:
        conn.execute(text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS activity_logs_fts USING fts5(
                id UNINDEXED,
                summary,
                source_path,
                rjcode,
                task_id,
                batch_id,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        ))
    except Exception:
        fts_available = False
        _db_logger.warning("[数据库] 当前 SQLite 不支持 FTS5，将回退为 LIKE 搜索", exc_info=True)

    if fts_available:
        # 仅当 FTS 表为空时回填，避免每次启动都做全量重建
        try:
            existing_fts_count = conn.execute(text("SELECT count(*) FROM activity_logs_fts")).scalar() or 0
            activity_count = conn.execute(text("SELECT count(*) FROM activity_logs")).scalar() or 0
            if existing_fts_count < activity_count:
                conn.execute(text(
                    """
                    INSERT INTO activity_logs_fts(id, summary, source_path, rjcode, task_id, batch_id)
                    SELECT id,
                           COALESCE(summary, ''),
                           COALESCE(source_path, ''),
                           COALESCE(rjcode, ''),
                           COALESCE(task_id, ''),
                           COALESCE(batch_id, '')
                      FROM activity_logs
                     WHERE id NOT IN (SELECT id FROM activity_logs_fts)
                    """
                ))
                _db_logger.info("[数据库] activity_logs_fts 初次回填完成")
        except Exception:
            _db_logger.warning("[数据库] activity_logs_fts 回填失败（非致命）", exc_info=True)

        for trigger_sql in (
            """
            CREATE TRIGGER IF NOT EXISTS activity_logs_fts_ai
            AFTER INSERT ON activity_logs BEGIN
              INSERT INTO activity_logs_fts(id, summary, source_path, rjcode, task_id, batch_id)
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
            """
            CREATE TRIGGER IF NOT EXISTS activity_logs_fts_ad
            AFTER DELETE ON activity_logs BEGIN
              DELETE FROM activity_logs_fts WHERE id = OLD.id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS activity_logs_fts_au
            AFTER UPDATE ON activity_logs BEGIN
              DELETE FROM activity_logs_fts WHERE id = OLD.id;
              INSERT INTO activity_logs_fts(id, summary, source_path, rjcode, task_id, batch_id)
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
