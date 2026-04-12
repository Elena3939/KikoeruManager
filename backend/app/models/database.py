from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean, Text, BigInteger, JSON, Index, text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import os

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
    has_dlsite = Column(Boolean, default=False, index=True)
    has_asmr_one = Column(Boolean, default=False, index=True)
    kikoeru_work_id = Column(Integer)
    asmr_one_cached_at = Column(DateTime)
    dlsite_cached_at = Column(DateTime)
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
            'has_dlsite': bool(self.has_dlsite),
            'has_asmr_one': bool(self.has_asmr_one),
            'kikoeru_work_id': self.kikoeru_work_id,
            'asmr_one_cached_at': self.asmr_one_cached_at.isoformat() if self.asmr_one_cached_at else None,
            'dlsite_cached_at': self.dlsite_cached_at.isoformat() if self.dlsite_cached_at else None,
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

    __table_args__ = (
        Index('idx_activity_created_category', 'created_at', 'category'),
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
        }


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
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

import logging
_db_logger = logging.getLogger(__name__)

# 数据库连接
def get_db_path():
    data_dir = os.environ.get('DATA_PATH', './data')
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, 'cache.db')
    # 转换为绝对路径
    db_path = os.path.abspath(db_path)
    return db_path

# 获取数据库路径
_db_path = get_db_path()

# 数据库连接，确保支持UTF-8
engine = create_engine(
    f'sqlite:///{_db_path}',
    connect_args={
        'check_same_thread': False,
    },
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
    _db_logger.info(f"[数据库] 表创建完成")

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
