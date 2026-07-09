import os
import yaml
import logging
import threading
import time
import tempfile
from typing import Optional, List, Callable
from pydantic import BaseModel, Field, model_validator
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from ..core.log_sanitizer import sanitize_for_log

class SynologyLibraryConfig(BaseModel):
    """群晖库存配置"""
    base_url: str = ""
    username: str = ""
    password: str = ""
    root_path: str = "/"
    session_name: str = "FileStation"
    timeout: int = 30
    verify_ssl: bool = True
    otp_code: str = ""
    device_name: str = ""
    device_id: str = ""
    enable_device_token: bool = True


class SynologyConnectionProfile(BaseModel):
    """群晖连接模板"""
    id: str = ""
    name: str = ""
    base_url: str = ""
    username: str = ""
    password: str = ""
    session_name: str = "FileStation"
    timeout: int = 30
    verify_ssl: bool = True
    otp_code: str = ""
    device_name: str = ""
    device_id: str = ""
    enable_device_token: bool = True


class LibraryConfigItem(BaseModel):
    """库存定义"""
    id: str = ""
    name: str = ""
    type: str = "local"
    path: str = ""
    browse_path: str = ""
    enabled: bool = True
    writable: bool = True
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    synology_profile_id: str = ""
    synology: Optional[SynologyLibraryConfig] = None


class StorageConfig(BaseModel):
    """存储路径配置"""
    input_path: str = "/input"
    temp_path: str = "/temp"
    library_path: str = "/library"
    processed_archives_path: str = "/processed"
    existing_folders_path: str = "/existing"  # 已存在文件夹目录（非软件解压的文件夹）
    asmr_subtitle_path: str = ""  # ASMR同步字幕文件夹路径
    synology_profiles: list[SynologyConnectionProfile] = Field(default_factory=list)
    libraries: list[LibraryConfigItem] = Field(default_factory=list)
    default_library_id: str = ""
    default_extract_library_id: str = ""
    health_warning_free_gb: float = 200.0
    stats_cache_ttl_seconds: int = 300
    remote_search_cache_ttl_seconds: int = 60
    remote_search_timeout_seconds: int = 30

class ClassificationRule(BaseModel):
    """分类规则"""
    type: str  # none, maker, series, rjcode
    enabled: bool = True
    path_template: str = ""  # 通用路径模板
    custom_name: Optional[str] = None  # 自定义目录名称（用于RJ号分类）
    fallback: Optional[str] = None
    max_tags: Optional[int] = None
    rjcode_range: Optional[str] = None  # RJ号范围，例如 "RJ01400000-RJ01499999"

class ProcessingConfig(BaseModel):
    """处理配置"""
    max_workers: int = 4
    retry_count: int = 3
    file_stable_checks: int = 3
    file_stable_interval: int = 2
    max_wait_time: int = 3600

class WatcherConfig(BaseModel):
    """监视器配置"""
    enabled: bool = True
    scan_interval: int = 30
    auto_start: bool = True
    auto_classify: bool = True
    delete_after_process: bool = False

class ExtractConfig(BaseModel):
    """解压配置"""
    seven_zip_path: str = "7z"
    # 可选：7-Zip ZS / 7z-zstd 兼容后端。用于官方 7zz 报 Unsupported Method
    # 的 7z/ZSTD 包（如 Method = Delta 04F71101），默认自动查找 7zzs/7z-zstd。
    seven_zip_zstd_path: str = ""
    auto_repair_extension: bool = True
    verify_after_extract: bool = True
    password_list: list = []
    filename_password_sniff_enabled: bool = True
    filename_password_sniff_templates: list[str] = Field(default_factory=lambda: [
        "{name}({password})",
        "{name}（{password}）",
    ])
    extract_nested_archives: bool = True  # 是否解压嵌套压缩包
    max_nested_depth: int = 5  # 最大嵌套深度
    # ZIP 文件名编码兜底代码页。解压前会先读中央目录自动嗅探；嗅探不到时才用这里。
    # 932=Shift-JIS（日语），936=GBK（简中），950=Big5（繁中），0=不强制代码页。
    zip_encoding: int = 932
    # 真正解压时同时跑几个 7z 子进程。
    # 0 = auto：启动时探测 storage.temp_path 所在盘类型自动决定
    #   · SSD/NVMe → min(processing.max_workers, 3)
    #   · HDD / 探测失败 / 网络盘 → 1（机械盘并发寻道严重伤性能伤寿命）
    # 1-N = 用户显式固定，跳过自动探测。
    # 多个 7z 进程在 HDD 上同时跑会让磁头疯狂寻道，亲测单包从 12 分钟 → 1.5 分钟。
    max_concurrent_extractions: int = 0
    # 传给 7z 的 -mmt 参数，控制单个 7z 进程的多线程档位。
    # "on" = 自动多线程（LZMA2 / deflate 都生效）；"off" = 单线程；"N" = 指定线程数。
    # 留空字符串则不加 -mmt 参数（用 7z 默认行为）。
    seven_zip_threads: str = "on"
    # 对 RAR 文件优先使用 unar 解压（默认开）。
    # 7zz 24.08 RAR 解析器不接受 -mcp 文件名编码参数，遇到日文 Shift-JIS / 中文 GBK
    # 命名的 RAR 时只能按本机 locale（Linux/Docker = UTF-8）解释 → 必然出乱码 →
    # 群晖 / NAS 文件管理器看到 ��� 替换字符无法访问。
    # unar 自带 ICU 文件名编码自动探测，对日文 / 中文 RAR 友好；unar 不可用或不识别
    # 该 RAR 变体时会自动回退到原 7zz 流程，所以打开是安全的。
    prefer_unar_for_rar: bool = True
    # 文件名乱码 guard 的全局逃生开关。默认关闭；开启后只记录诊断，不阻断入库。
    bypass_filename_garbled_check: bool = False

class FilterRule(BaseModel):
    """过滤规则"""
    name: str
    pattern: str
    target: str = "file"  # file, folder, all
    action: str = "exclude"  # exclude, include
    enabled: bool = True

class SubtitleFilterRule(BaseModel):
    """字幕候选过滤规则"""
    name: str = ""
    pattern: str = ""
    target: str = "name"  # name, path, all
    enabled: bool = True

class FilterConfig(BaseModel):
    """过滤配置"""
    enabled: bool = True
    filter_dir: bool = True
    rules: list[FilterRule] = []

class MetadataConfig(BaseModel):
    """元数据配置"""
    locale: str = "zh_cn"
    connect_timeout: int = 10
    read_timeout: int = 10
    sleep_interval: int = 3
    http_proxy: Optional[str] = None
    cache_enabled: bool = True
    fetch_cover: bool = True
    make_folder_icon: bool = True
    remove_jpg_file: bool = True

class RenameConfig(BaseModel):
    """重命名配置"""
    template: str = "{rjcode} {work_name}"
    date_format: str = "%y%m%d"
    delimiter: str = " "
    cv_list_left: str = "(CV "
    cv_list_right: str = ")"
    exclude_square_brackets: bool = False
    illegal_char_to_full_width: bool = False
    tags_max_number: int = 5
    tags_ordered_list: list = []
    flatten_single_subfolder: bool = True  # 启用扁平化单一层级文件夹
    flatten_depth: int = 3  # 扁平化深度，最多处理多少层嵌套的单子文件夹（默认3层）
    remove_empty_folders: bool = True  # 过滤后是否移除空文件夹
    api_rename_follow_template: bool = False  # API重命名是否遵循重命名模板
    use_japanese_metadata: bool = False  # 使用日语元数据填充模板（除rjcode和work_name外）

class PasswordCleanupConfig(BaseModel):
    """密码库智能清理配置"""
    enabled: bool = False  # 是否启用智能清理
    max_use_count: int = 1  # 使用次数阈值，小于等于此值的密码将被清理
    cron_expression: str = "0 0 * * 0"  # Cron表达式，默认每周日午夜执行
    preserve_days: int = 30  # 保留天数，密码创建后超过此天数且使用次数<=阈值才删除
    exclude_sources: list = []  # 排除的来源类型，如 ["manual"] 表示不删除手动添加的密码

class ProcessedArchiveCleanupConfig(BaseModel):
    """已处理压缩包智能清理配置"""
    enabled: bool = False  # 是否启用智能清理
    cron_expression: str = "0 1 * * 0"  # Cron表达式，默认每周日凌晨1点执行
    # 清理策略（多选）
    strategy: str = "age"  # age: 按时间, count: 按数量, size: 按容量
    # 按时间清理
    preserve_days: int = 30  # 保留天数，处理超过此天数的压缩包
    # 按数量清理
    max_count: int = 1000  # 最大保留数量，超过此数量删除最旧的
    # 按容量清理
    max_size_gb: float = 50.0  # 最大占用空间(GB)，超过此容量删除最旧的
    # 其他选项
    exclude_reprocessing: bool = True  # 是否排除正在重新处理的压缩包
    # 启动扫描配置
    scan_on_startup: bool = True  # 启动时是否扫描已处理压缩包目录
    min_keep_count: int = 10  # 最小保留数量，无论其他条件如何都保留最近的N个

class PathMappingRule(BaseModel):
    """路径映射规则"""
    remote_path: str  # 远程/Docker中的路径，如 /viocelink
    local_path: str   # 本地映射路径，如 W:\Viocelink 或 \\server\share
    enabled: bool = True

class PathMappingConfig(BaseModel):
    """路径映射配置"""
    enabled: bool = False  # 是否启用路径映射
    rules: list[PathMappingRule] = []  # 映射规则列表
    # 打开方式
    open_mode: str = "auto"  # auto: 自动判断, direct: 直接打开(同设备), mapped: 使用映射路径(跨设备)

class KikoeruServerConfig(BaseModel):
    """Kikoeru 服务器查重配置"""
    enabled: bool = False  # 是否启用 Kikoeru 服务器查重
    server_url: str = ""   # Kikoeru 服务器地址，如 http://192.168.1.100:8088
    username: str = ""     # 登录用户名
    password: str = ""     # 登录密码
    api_token: str = ""    # API 访问令牌（自动获取）
    token_expires: int = 0 # Token 过期时间戳
    timeout: int = 10      # 请求超时(秒)
    cache_ttl: int = 300   # 缓存时间(秒)
    enable_fuzzy_rj_match: bool = False  # 是否允许危险的 RJ ±1 宽容匹配
    http_proxy: Optional[str] = None  # HTTP 代理地址（已禁用，远程服务器连接使用直连模式）
    check_in_preextract: bool = True  # 是否在解压预检中启用远程查重
    retry_count: int = 3   # 网络请求重试次数
    retry_delay: float = 1.0  # 重试间隔(秒)

class ASMRSyncConfig(BaseModel):
    """ASMR 同步下载配置"""
    enabled: bool = True
    api_base_url: str = "https://api.asmr-200.com/api"
    max_concurrent_downloads: int = 3
    enhanced_max_parallel_sessions: int = 5
    enhanced_per_session_concurrency: int = 5
    queue_worker_limit: int = 5
    http_proxy: Optional[str] = None
    retry_interval_hours: float = 1.0# 重试间隔（小时）
    max_retry_count: int = 10  # 最大重试次数
    retry_cron: str = "0 */1 * * *"# 重试cron表达式（默认每小时执行一次）
    retry_count: int = 3
    retry_delay: int = 5
    download_timeout_seconds: int = 60
    verify_md5_after_download: bool = True
    md5_verify_required: bool = True
    auto_upload_enabled: bool = False
    auto_upload_mode: str = "local"
    auto_upload_library_id: str = ""
    auto_upload_target_path: str = ""
    match_duration_tolerance_seconds: float = 3.0
    match_size_tolerance_ratio: float = 0.08
    # LRC广告清理配置
    lrc_clean_enabled: bool = True  # 是否启用LRC广告清理
    lrc_clean_patterns: List[str] = [  # 自定义清理规则（正则表达式）
        r'@[\w]{3,}',  # Telegram账号
        r'Telegram',
        r'telegram',
        r'电报',
        r'tg群',
        r'TG群',
        r'QQ群[：:]\s*\d+',
        r'群号[：:]\s*\d+',
    ]
    # 字幕繁简转换配置
    simplify_chinese_enabled: bool = True  # 是否启用字幕繁体转简体

class PikPakAccountConfig(BaseModel):
    """PikPak 多账号配置"""
    id: str = ""
    label: str = ""
    enabled: bool = True
    username: str = ""
    password: str = ""
    encoded_token: str = ""
    device_id: str = ""
    transfer_dir: str = "/KikoeruManager"


class HttpDownloaderConfig(BaseModel):
    """HTTP 外链下载配置"""
    enabled: bool = True
    engine: str = "aria2"
    download_root: str = ""
    aria2_path: str = "aria2c"
    proxy_url: str = ""
    proxy_platforms: List[str] = Field(default_factory=lambda: ["http", "gofile", "transferit", "onedrive", "google_drive", "pikpak"])
    max_concurrent_downloads: int = 3
    split: int = 8
    max_connection_per_server: int = 8
    min_split_size: str = "1M"
    gofile_max_concurrent_downloads: int = 2
    gofile_split: int = 5
    retry_count: int = 5
    retry_wait_seconds: int = 5
    connect_timeout_seconds: int = 15
    timeout_seconds: int = 60
    allow_private_network: bool = False
    conflict_policy: str = "resume"
    gofile_token: str = ""
    google_drive_oauth_enabled: bool = False
    google_drive_oauth_client_mode: str = "builtin"
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""
    google_drive_refresh_token: str = ""
    google_drive_account_name: str = ""
    google_drive_account_email: str = ""
    google_drive_account_avatar_url: str = ""
    google_drive_account_permission_id: str = ""
    google_drive_account_cached_at: int = 0
    google_drive_oauth_expired: bool = False
    pikpak_enabled: bool = False
    pikpak_default_enabled: bool = True
    pikpak_label: str = ""
    pikpak_username: str = ""
    pikpak_password: str = ""
    pikpak_encoded_token: str = ""
    pikpak_device_id: str = ""
    pikpak_transfer_dir: str = "/KikoeruManager"
    pikpak_auto_save_share: bool = True
    pikpak_accounts: List[PikPakAccountConfig] = Field(default_factory=list)


class BaiduNetdiskConfig(BaseModel):
    """百度网盘下载配置。"""
    enabled: bool = False
    download_root: str = ""
    upload_default_remote_dir: str = "/KikoeruManager"
    upload_conflict_policy: str = "skip"
    upload_max_parallel: int = 4
    upload_max_load: int = 4
    baidupcs_go_path: str = ""
    config_dir: str = ""
    share_code_separator: str = "----"
    cookie: str = ""
    max_parallel: int = 20
    max_download_load: int = 5
    conflict_policy: str = "resume"
    svip_speed_enabled: bool = True
    account_name: str = ""
    account_netdisk_name: str = ""
    account_avatar_url: str = ""
    account_uk: str = ""
    vip_type: int = 0
    vip_label: str = ""
    vip_level: str = ""
    vip_expire_at: int = 0
    quota_bytes: int = 0
    used_bytes: int = 0
    account_cached_at: int = 0

class AutoProcessConfig(BaseModel):
    """正常解压缩流程步骤配置"""
    check_duplicate: bool = True  # 预检重复
    import_linked_translation_subtitles: bool = True  # 命中关联原作且原作无字幕时，自动仅导入字幕
    extract: bool = True  # 解压（不建议关闭）
    fetch_metadata: bool = True  # 获取元数据
    rename: bool = True  # 重命名
    filter: bool = True  # 过滤
    classify: bool = True  # 智能分类
    archive: bool = True  # 归档压缩包

class ProcessExistingFolderConfig(BaseModel):
    """已有文件夹处理流程步骤配置"""
    check_duplicate: bool = True  # 预检重复
    fetch_metadata: bool = True  # 获取元数据
    rename: bool = True  # 重命名
    filter: bool = True  # 过滤
    import_lrc: bool = True  # LRC导入
    classify: bool = True  # 智能分类

class ASMRSyncStepConfig(BaseModel):
    """ASMR同步下载流程步骤配置"""
    download: bool = True  # 下载文件（不建议关闭）
    sync_subtitle: bool = True  # 同步字幕
    rename: bool = True  # 重命名
    classify: bool = True  # 智能分类
    move_subtitle_folder: bool = True  # 移动字幕文件夹

class RJSubtitleConfig(BaseModel):
    """RJ 字幕抓取配置"""
    overwrite_existing: bool = False
    scan_one_level_only: bool = True
    scan_depth: int = 3
    enable_metadata_match: bool = True
    skip_if_existing_subtitles: bool = False
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: list[SubtitleFilterRule] = []
    auto_import_use_filter_rules: bool = True
    auto_import_filter_rules: list[FilterRule] = []
    show_source_search: bool = True
    show_written_files: bool = True
    show_download_progress: bool = True
    show_issues: bool = True


class AISubtitleMatchingConfig(BaseModel):
    """AI 字幕配对配置。"""
    enabled: bool = False
    auto_apply_enabled: bool = False
    manual_assist_enabled: bool = True
    default_mode: str = "rule_ai_auto"
    model: str = ""
    api_key: str = ""
    api_base: str = ""
    api_version: str = ""
    organization: str = ""
    proxy_url: str = ""
    timeout_seconds: int = 30
    max_retries: int = 2
    temperature: float = 0
    confidence_threshold: int = 85
    max_items_per_request: int = 120
    prompt_template: str = (
        "你是字幕文件名匹配器。你只能根据文件名判断音频和字幕组是否对应。\n"
        "不要假设文件内容、字幕正文、音频时长、音频 metadata 或目录路径。\n"
        "输入包含 audio_files 与 subtitle_groups。每项只有 id 和 filename/base_name。\n"
        "请只输出 JSON，格式为：\n"
        '{"matches":[{"audio_id":"a1","subtitle_group_id":"g1","confidence":0,"reason":"简短中文原因"}],'
        '"unmatched_audio_ids":[],"unmatched_subtitle_group_ids":[]}\n'
        "规则：一个 audio_id 最多匹配一个 subtitle_group_id；一个 subtitle_group_id 最多使用一次；"
        "文件名完全对应、轨道号对应、标题规范化后对应时给高分；不确定就放入 unmatched。"
    )

class BackupZipConfig(BaseModel):
    enabled: bool = False
    source_path: str = ""
    output_dir: str = ""
    path_copy_target: str = ""
    copy_structure_before_zip: bool = True
    password: str = ""
    archive_format: str = "zip"
    compression_level: int = 9
    compression_threads: int = 0
    dictionary_size_mb: int = 0    # 0=自动根据压缩级别选择
    solid_archive: bool = True     # 7z格式启用固实压缩（提升压缩率）
    baidu_upload_enabled: bool = False
    baidu_upload_remote_dir: str = "/KikoeruManager"
    baidu_upload_create_subdir: str = ""
    baidu_upload_conflict_policy: str = "skip"
    baidu_upload_cleanup_local_archive: bool = False

class EmailWatcherConfig(BaseModel):
    """DLsite 邮件监听配置（IMAP IDLE + fallback 轮询）"""
    enabled: bool = False
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_ssl: bool = True
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    sender_filter: str = "dlsite.com"       # 只处理来自该域名的邮件
    subject_filter: str = ""                  # 主题关键词（空字符串=不过滤）
    mark_as_read: bool = True               # 处理后标记已读
    move_to_folder: str = ""               # 处理后移入指定文件夹（空=不移动）
    auto_index_new_circles: bool = True     # 首次出现的社团自动全量索引
    idle_timeout_minutes: int = 25         # 单次 IDLE 等待超时（分钟），RFC 上限 29
    fallback_poll_interval_seconds: int = 300  # IDLE 失败后降级轮询间隔

class NotificationEmailConfig(BaseModel):
    """任务通知邮件配置（SMTP 发件）"""
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_ssl: bool = True
    smtp_starttls: bool = False
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "KikoeruManager"
    to_email: str = ""
    connect_timeout_seconds: int = 10
    send_timeout_seconds: int = 30
    max_retry_count: int = 3
    retry_interval_seconds: int = 60
    send_on_completed: bool = True
    send_on_failed: bool = True
    send_on_waiting_manual: bool = True
    send_on_cancelled: bool = False
    # 推送域过滤：空列表 = 全部 domain 都发；非空时只发清单内的 domain
    # 可选值参考 TaskCenterService.DOMAIN_LABELS 的 key（all 除外）
    enabled_domains: list[str] = []


class NotificationCenterConfig(BaseModel):
    """站内通知中心配置"""
    enabled: bool = True
    retain_days: int = 30
    max_items: int = 200
    poll_interval_seconds: int = 20
    unread_highlight_enabled: bool = True


class RedisConfig(BaseModel):
    """Redis 运行态配置。PostgreSQL 仍是事实源，Redis 只承载短期运行态。"""
    enabled: bool = True
    required: bool = True
    url: str = "redis://localhost:6379/0"
    namespace: str = "kikoerumanager"
    environment: str = "prod"
    socket_timeout_seconds: float = 2.0
    connect_timeout_seconds: float = 2.0
    runtime_ttl_seconds: int = 259200
    short_cache_ttl_seconds: int = 60
    event_stream_maxlen: int = 50000
    dirty_stream_maxlen: int = 200000

    @model_validator(mode='after')
    def normalize_runtime_values(self):
        namespace = str(self.namespace or "kikoerumanager").strip() or "kikoerumanager"
        if namespace.lower() in {"prekikoeru", "kikoerutool", "kikoerutool_elena"}:
            namespace = "kikoerumanager"
        self.namespace = namespace
        self.environment = str(self.environment or "prod").strip() or "prod"
        self.socket_timeout_seconds = max(0.1, float(self.socket_timeout_seconds or 2.0))
        self.connect_timeout_seconds = max(0.1, float(self.connect_timeout_seconds or 2.0))
        self.runtime_ttl_seconds = max(60, int(self.runtime_ttl_seconds or 259200))
        self.short_cache_ttl_seconds = max(1, int(self.short_cache_ttl_seconds or 60))
        self.event_stream_maxlen = max(100, int(self.event_stream_maxlen or 50000))
        self.dirty_stream_maxlen = max(100, int(self.dirty_stream_maxlen or 200000))
        return self


class BonusProbeConfig(BaseModel):
    """DLsite 特典补全运行配置。"""
    max_active_jobs: int = 1
    normal_batch_size: int = 500
    normal_concurrency: int = 3
    deep_batch_size: int = 500
    deep_concurrency: int = 3
    new_release_batch_size: int = 100
    new_release_concurrency: int = 2
    max_batch_size: int = 500
    max_concurrency: int = 3
    cache_lookup_batch_size: int = 500
    cache_write_batch_size: int = 100

    @model_validator(mode='after')
    def normalize_limits(self):
        self.max_active_jobs = max(1, int(self.max_active_jobs or 1))
        self.max_batch_size = max(1, int(self.max_batch_size or 500))
        self.max_concurrency = min(max(1, int(self.max_concurrency or 3)), 3)
        self.normal_batch_size = min(max(1, int(self.normal_batch_size or 500)), self.max_batch_size)
        self.normal_concurrency = min(max(1, int(self.normal_concurrency or 3)), self.max_concurrency)
        self.deep_batch_size = min(max(1, int(self.deep_batch_size or 500)), self.max_batch_size)
        self.deep_concurrency = min(max(1, int(self.deep_concurrency or 3)), self.max_concurrency)
        self.new_release_batch_size = min(max(1, int(self.new_release_batch_size or 100)), self.max_batch_size)
        self.new_release_concurrency = min(max(1, int(self.new_release_concurrency or 2)), self.max_concurrency)
        self.cache_lookup_batch_size = max(100, int(self.cache_lookup_batch_size or 500))
        self.cache_write_batch_size = min(max(20, int(self.cache_write_batch_size or 100)), 100)
        return self


class ResourceBudgetConfig(BaseModel):
    """跨业务资源预算：限制慢盘、远程库、下载等链路互相打满。"""
    enabled: bool = True
    disk_io_local: int = 2
    archive_cpu: int = 0
    archive_inspect: int = 0
    remote_fs: int = 4
    network_download: int = 5
    database_write: int = 4
    library_index_write: int = 1
    bonus_probe_database_write: int = 1

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_database_write_key(cls, data):
        legacy_key = 'sqli' + 'te_write'
        if isinstance(data, dict) and 'database_write' not in data and legacy_key in data:
            data = dict(data)
            data['database_write'] = data.pop(legacy_key)
        return data


class DatabaseConfig(BaseModel):
    """PostgreSQL 运行配置。DATABASE_URL 存在时优先使用环境变量。"""
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "kikoerumanager"
    username: str = "kikoerumanager"
    password: str = ""
    sslmode: str = "prefer"
    connect_timeout_seconds: int = 10
    pool_size: int = 10
    max_overflow: int = 20
    pool_recycle_seconds: int = 1800
    pool_timeout_seconds: int = 30
    statement_timeout_ms: int = 120000
    startup_health_check: bool = True
    slow_query_monitor_enabled: bool = True
    slow_query_threshold_ms: int = 500
    auto_explain_enabled: bool = False
    auto_explain_threshold_ms: int = 1000
    search_backend: str = "pg_trgm"

    @model_validator(mode='before')
    @classmethod
    def migrate_legacy_embedded_db_config(cls, data):
        if not isinstance(data, dict):
            return data
        legacy_keys = {
            'journal_mode',
            'synchronous',
            'busy_timeout_ms',
            'wal_autocheckpoint',
            'cache_size_kb',
            'startup_quick_check',
            'startup_integrity_check',
        }
        if not any(key in data for key in legacy_keys):
            return data
        cleaned = {k: v for k, v in dict(data).items() if k not in legacy_keys}
        if 'pool_size' not in cleaned:
            cleaned['pool_size'] = 10
        if 'max_overflow' not in cleaned:
            cleaned['max_overflow'] = 20
        return cleaned


class SecurityGateConfig(BaseModel):
    """Google Authenticator 系统门禁配置"""
    enabled: bool = False
    secret: str = ""
    pending_secret: str = ""
    allow_remember_device: bool = True
    session_hours: int = 8
    remember_days: int = 30
    blacklist_enabled: bool = True
    failure_window_minutes: int = 10
    max_failures: int = 5
    trust_proxy_headers: bool = False
    email_alert_enabled: bool = True
    email_alert_on_failure: bool = False
    email_alert_on_blacklist: bool = True
    email_alert_on_blocked_visit: bool = False
    email_alert_on_reset: bool = True
    email_alert_min_interval_seconds: int = 300


class LibraryUiConfig(BaseModel):
    """库存页 UI 偏好"""
    view_mode: str = "directory"

    @model_validator(mode='before')
    @classmethod
    def normalize_view_mode(cls, data):
        if isinstance(data, dict):
            mode = str(data.get('view_mode') or 'directory').strip().lower()
            data = dict(data)
            data['view_mode'] = mode if mode in {'directory', 'circle'} else 'directory'
        return data


class UiConfig(BaseModel):
    """页面级 UI 偏好配置"""
    library: LibraryUiConfig = LibraryUiConfig()


class AppConfig(BaseModel):
    """应用配置"""
    storage: StorageConfig = StorageConfig()
    processing: ProcessingConfig = ProcessingConfig()
    watcher: WatcherConfig = WatcherConfig()
    extract: ExtractConfig = ExtractConfig()
    filter: FilterConfig = FilterConfig(
        enabled=True,
        filter_dir=True,
        rules=[
            FilterRule(name="过滤无SE的WAV文件", pattern=r"(?:SE|音|音效)(?:[な無]し|CUT).*\.WAV$", target="file", action="exclude", enabled=True),
            FilterRule(name="过滤MP3文件", pattern=r"\.mp3$", target="file", action="exclude", enabled=False),
        ]
    )
    metadata: MetadataConfig = MetadataConfig()
    rename: RenameConfig = RenameConfig()
    classification: list[ClassificationRule] = [
        ClassificationRule(type="none", enabled=True, path_template="", custom_name=None, fallback=None, max_tags=None, rjcode_range=None),
    ]
    password_cleanup: PasswordCleanupConfig = PasswordCleanupConfig()
    processed_archive_cleanup: ProcessedArchiveCleanupConfig = ProcessedArchiveCleanupConfig()
    path_mapping: PathMappingConfig = PathMappingConfig()
    kikoeru_server: KikoeruServerConfig = KikoeruServerConfig()
    asmr_sync: ASMRSyncConfig = ASMRSyncConfig()
    http_downloader: HttpDownloaderConfig = HttpDownloaderConfig()
    baidu_netdisk: BaiduNetdiskConfig = BaiduNetdiskConfig()
    auto_process: AutoProcessConfig = AutoProcessConfig()
    process_existing: ProcessExistingFolderConfig = ProcessExistingFolderConfig()
    asmr_sync_step: ASMRSyncStepConfig = ASMRSyncStepConfig()
    rj_subtitle: RJSubtitleConfig = RJSubtitleConfig()
    ai_subtitle_matching: AISubtitleMatchingConfig = AISubtitleMatchingConfig()
    backup_zip: BackupZipConfig = BackupZipConfig()
    email_watcher: EmailWatcherConfig = EmailWatcherConfig()
    notification_email: NotificationEmailConfig = NotificationEmailConfig()
    notification_center: NotificationCenterConfig = NotificationCenterConfig()
    redis: RedisConfig = RedisConfig()
    bonus_probe: BonusProbeConfig = BonusProbeConfig()
    resource_budget: ResourceBudgetConfig = ResourceBudgetConfig()
    database: DatabaseConfig = DatabaseConfig()
    security_gate: SecurityGateConfig = SecurityGateConfig()
    ui: UiConfig = UiConfig()

# 全局配置实例
_config: Optional[AppConfig] = None
_config_loaded_path: str = ""
_config_loaded_mtime: float = 0.0
_config_last_error: str = ""
_config_write_in_progress: bool = False
_config_reload_in_progress: bool = False


def _resolve_config_path(config_path: str = None) -> str:
    if config_path is None:
        env_config_path = os.environ.get('CONFIG_PATH')
        if env_config_path:
            config_path = env_config_path
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
            config_path = os.path.join(project_root, 'data', 'config', 'config.yaml')
    return os.path.abspath(config_path)


def _write_yaml_atomically(config_path: str, payload: dict) -> float:
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.config.', suffix='.yaml.tmp', dir=config_dir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            yaml.dump(payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, config_path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    try:
        return os.path.getmtime(config_path)
    except OSError:
        return 0.0

def load_config(config_path: str = None) -> AppConfig:
    """加载配置"""
    global _config, _config_loaded_path, _config_loaded_mtime, _config_last_error, _config_reload_in_progress
    logger = logging.getLogger(__name__)
    with _config_lock:
        _config_reload_in_progress = True
        try:
            config_path = _resolve_config_path(config_path)
            if os.environ.get('CONFIG_PATH'):
                logger.info(f"从环境变量 CONFIG_PATH 读取配置路径: {config_path}")

            _config_loaded_path = config_path
            logger.info(f"[CONFIG] 尝试加载配置文件: {config_path}")
            logger.info(f"[CONFIG] 配置文件是否存在: {os.path.exists(config_path)}")

            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = yaml.safe_load(f) or {}

                    logger.info(
                        "YAML 配置已加载: path=%s top_keys=%s classification=%s",
                        config_path,
                        len(config_data),
                        len(config_data.get('classification', []) or []),
                    )
                    logger.debug("YAML 配置顶层键: %s", sorted(config_data.keys()))

                    if 'classification' in config_data and config_data['classification']:
                        validated_rules = []
                        for rule_data in config_data['classification']:
                            try:
                                rule_data_cleaned = dict(rule_data)
                                if 'path_template' not in rule_data_cleaned or rule_data_cleaned['path_template'] is None:
                                    rule_data_cleaned['path_template'] = ''
                                rule = ClassificationRule(**rule_data_cleaned)
                                validated_rules.append(rule)
                            except Exception as e:
                                logger.warning(f"分类规则加载失败: {rule_data}, 错误: {e}, 使用默认规则")
                        if validated_rules:
                            config_data['classification'] = [r.model_dump() for r in validated_rules]
                        else:
                            config_data['classification'] = [
                                ClassificationRule(type="none", enabled=True, path_template="", custom_name=None, fallback=None, max_tags=None, rjcode_range=None).model_dump()
                            ]

                    if 'filter' in config_data and config_data['filter'] and 'rules' in config_data['filter'] and config_data['filter']['rules']:
                        validated_filter_rules = []
                        for rule_data in config_data['filter']['rules']:
                            try:
                                if 'target' not in rule_data or not rule_data['target']:
                                    rule_data['target'] = 'file'
                                rule = FilterRule(**rule_data)
                                validated_filter_rules.append(rule)
                            except Exception as e:
                                logger.warning(f"过滤规则加载失败: {rule_data}, 错误: {e}, 跳过此规则")
                        if validated_filter_rules:
                            config_data['filter']['rules'] = [r.model_dump() for r in validated_filter_rules]

                    if 'rename' in config_data:
                        if 'flatten_single_subfolder' not in config_data['rename']:
                            config_data['rename']['flatten_single_subfolder'] = True
                            logger.info("添加缺失的 flatten_single_subfolder 配置，默认为 True")
                        if 'flatten_depth' not in config_data['rename']:
                            config_data['rename']['flatten_depth'] = 3
                            logger.info("添加缺失的 flatten_depth 配置，默认为 3")
                        if 'remove_empty_folders' not in config_data['rename']:
                            config_data['rename']['remove_empty_folders'] = True
                            logger.info("添加缺失的 remove_empty_folders 配置，默认为 True")
                        if 'api_rename_follow_template' not in config_data['rename']:
                            config_data['rename']['api_rename_follow_template'] = False
                            logger.info("添加缺失的 api_rename_follow_template 配置，默认为 False")
                        if 'use_japanese_metadata' not in config_data['rename']:
                            config_data['rename']['use_japanese_metadata'] = False
                            logger.info("添加缺失的 use_japanese_metadata 配置，默认为 False")
                        logger.debug(f"[CONFIG] rename.template = '{config_data['rename'].get('template', 'NOT SET')}'")

                    if 'password_cleanup' not in config_data or not config_data['password_cleanup']:
                        config_data['password_cleanup'] = {
                            'enabled': False,
                            'max_use_count': 1,
                            'cron_expression': '0 0 * * 0',
                            'preserve_days': 30,
                            'exclude_sources': []
                        }
                        logger.info("添加缺失的 password_cleanup 配置，使用默认值")
                    else:
                        if 'enabled' not in config_data['password_cleanup']:
                            config_data['password_cleanup']['enabled'] = False
                        if 'max_use_count' not in config_data['password_cleanup']:
                            config_data['password_cleanup']['max_use_count'] = 1
                        if 'cron_expression' not in config_data['password_cleanup']:
                            config_data['password_cleanup']['cron_expression'] = '0 0 * * 0'
                        if 'preserve_days' not in config_data['password_cleanup']:
                            config_data['password_cleanup']['preserve_days'] = 30
                        if 'exclude_sources' not in config_data['password_cleanup']:
                            config_data['password_cleanup']['exclude_sources'] = []

                    if 'processed_archive_cleanup' not in config_data or not config_data['processed_archive_cleanup']:
                        config_data['processed_archive_cleanup'] = {
                            'enabled': False,
                            'strategy': 'age',
                            'cron_expression': '0 1 * * 0',
                            'preserve_days': 30,
                            'max_count': 1000,
                            'max_size_gb': 50,
                            'exclude_reprocessing': True
                        }
                        logger.info("添加缺失的 processed_archive_cleanup 配置，使用默认值")
                    else:
                        if 'enabled' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['enabled'] = False
                        if 'strategy' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['strategy'] = 'age'
                        if 'cron_expression' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['cron_expression'] = '0 1 * * 0'
                        if 'preserve_days' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['preserve_days'] = 30
                        if 'max_count' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['max_count'] = 1000
                        if 'max_size_gb' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['max_size_gb'] = 50
                        if 'exclude_reprocessing' not in config_data['processed_archive_cleanup']:
                            config_data['processed_archive_cleanup']['exclude_reprocessing'] = True

                    if 'auto_process' not in config_data or not config_data['auto_process']:
                        config_data['auto_process'] = {
                            'check_duplicate': True,
                            'import_linked_translation_subtitles': True,
                            'extract': True,
                            'fetch_metadata': True,
                            'rename': True,
                            'filter': True,
                            'classify': True,
                            'archive': True
                        }
                        logger.info("添加缺失的 auto_process 配置，使用默认值")
                    else:
                        defaults = {
                            'check_duplicate': True,
                            'import_linked_translation_subtitles': True,
                            'extract': True,
                            'fetch_metadata': True,
                            'rename': True,
                            'filter': True,
                            'classify': True,
                            'archive': True
                        }
                        for key, value in defaults.items():
                            if key not in config_data['auto_process']:
                                config_data['auto_process'][key] = value

                    if 'process_existing' not in config_data or not config_data['process_existing']:
                        config_data['process_existing'] = {
                            'check_duplicate': True,
                            'fetch_metadata': True,
                            'rename': True,
                            'filter': True,
                            'import_lrc': True,
                            'classify': True
                        }
                        logger.info("添加缺失的 process_existing 配置，使用默认值")
                    else:
                        defaults = {
                            'check_duplicate': True,
                            'fetch_metadata': True,
                            'rename': True,
                            'filter': True,
                            'import_lrc': True,
                            'classify': True
                        }
                        for key, value in defaults.items():
                            if key not in config_data['process_existing']:
                                config_data['process_existing'][key] = value

                    if 'asmr_sync_step' not in config_data or not config_data['asmr_sync_step']:
                        config_data['asmr_sync_step'] = {
                            'download': True,
                            'sync_subtitle': True,
                            'rename': True,
                            'classify': True,
                            'move_subtitle_folder': True
                        }
                        logger.info("添加缺失的 asmr_sync_step 配置，使用默认值")
                    else:
                        defaults = {
                            'download': True,
                            'sync_subtitle': True,
                            'rename': True,
                            'classify': True,
                            'move_subtitle_folder': True
                        }
                        for key, value in defaults.items():
                            if key not in config_data['asmr_sync_step']:
                                config_data['asmr_sync_step'][key] = value

                    if 'http_downloader' not in config_data or not config_data['http_downloader']:
                        config_data['http_downloader'] = HttpDownloaderConfig().model_dump()
                        logger.info("添加缺失的 http_downloader 配置，使用默认值")
                    else:
                        defaults = HttpDownloaderConfig().model_dump()
                        for key, value in defaults.items():
                            if key not in config_data['http_downloader']:
                                config_data['http_downloader'][key] = value

                    if 'baidu_netdisk' not in config_data or not config_data['baidu_netdisk']:
                        config_data['baidu_netdisk'] = BaiduNetdiskConfig().model_dump()
                        logger.info("添加缺失的 baidu_netdisk 配置，使用默认值")
                    else:
                        defaults = BaiduNetdiskConfig().model_dump()
                        for key, value in defaults.items():
                            if key not in config_data['baidu_netdisk']:
                                config_data['baidu_netdisk'][key] = value
                        if not str(config_data['baidu_netdisk'].get('baidupcs_go_path') or '').strip():
                            config_data['baidu_netdisk']['baidupcs_go_path'] = defaults['baidupcs_go_path']

                    if 'rj_subtitle' not in config_data or not config_data['rj_subtitle']:
                        config_data['rj_subtitle'] = {
                            'overwrite_existing': False,
                            'scan_one_level_only': True,
                            'scan_depth': 3,
                            'enable_metadata_match': True,
                            'skip_if_existing_subtitles': False,
                            'naming_strategy': 'audio',
                            'use_filter_rules': False,
                            'subtitle_filter_rules': [],
                            'show_source_search': True,
                            'show_written_files': True,
                            'show_download_progress': True,
                            'show_issues': True
                        }
                        logger.info("添加缺失的 rj_subtitle 配置，使用默认值")
                    else:
                        defaults = {
                            'overwrite_existing': False,
                            'scan_one_level_only': True,
                            'scan_depth': 3,
                            'enable_metadata_match': True,
                            'skip_if_existing_subtitles': False,
                            'naming_strategy': 'audio',
                            'use_filter_rules': False,
                            'subtitle_filter_rules': [],
                            'show_source_search': True,
                            'show_written_files': True,
                            'show_download_progress': True,
                            'show_issues': True
                        }
                        for key, value in defaults.items():
                            if key not in config_data['rj_subtitle']:
                                config_data['rj_subtitle'][key] = value

                    if 'backup_zip' not in config_data or not config_data['backup_zip']:
                        config_data['backup_zip'] = BackupZipConfig().model_dump()
                    else:
                        defaults = BackupZipConfig().model_dump()
                        for key, value in defaults.items():
                            if key not in config_data['backup_zip']:
                                config_data['backup_zip'][key] = value

                    _config = AppConfig(**config_data)
                    _config_loaded_mtime = os.path.getmtime(config_path) if os.path.exists(config_path) else 0.0
                    _config_last_error = ""
                    logger.info(
                        "[CONFIG] 配置加载完成: path=%s top_keys=%s libraries=%s classification=%s template=%r",
                        config_path,
                        len(config_data),
                        len(_config.storage.libraries),
                        len(_config.classification),
                        _config.rename.template,
                    )
                    logger.debug(
                        "[CONFIG] 存储路径摘要: %s",
                        sanitize_for_log({
                            "input_path": _config.storage.input_path,
                            "library_path": _config.storage.library_path,
                            "temp_path": _config.storage.temp_path,
                            "processed_archives_path": _config.storage.processed_archives_path,
                        }),
                    )
                    for i, rule in enumerate(_config.classification):
                        logger.debug(f"规则 {i}: type={rule.type}, enabled={rule.enabled}, custom_name={rule.custom_name}")
                except Exception as e:
                    _config_last_error = str(e)
                    logger.error(f"配置文件加载失败，使用默认配置: {e}")
                    _config = AppConfig()
                    _config_loaded_mtime = 0.0
            else:
                logger.info("配置文件不存在，使用默认配置")
                _config = AppConfig()
                _config_last_error = ""
                _config_loaded_mtime = _write_yaml_atomically(config_path, _config.model_dump())
                logger.info(f"默认配置已保存到: {config_path}")
            return _config
        finally:
            _config_reload_in_progress = False

def get_config() -> AppConfig:
    """获取配置"""
    if _config is None:
        return load_config()
    if _config_write_in_progress or _config_reload_in_progress:
        return _config
    config_path = _config_loaded_path or os.path.abspath(get_config_file_path())
    try:
        current_mtime = os.path.getmtime(config_path)
    except OSError:
        current_mtime = 0.0
    if config_path and current_mtime and current_mtime != _config_loaded_mtime:
        logging.getLogger(__name__).info(f"[CONFIG] 检测到配置文件变更，自动重新加载: {config_path}")
        return load_config(config_path)
    return _config

def deep_merge(base: dict, update: dict) -> dict:
    """深度合并两个字典"""
    result = base.copy()
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def save_config(config_data: dict, config_path: str = None) -> AppConfig:
    """保存配置到文件（支持部分更新）"""
    global _config, _config_loaded_path, _config_loaded_mtime, _config_last_error, _config_write_in_progress
    
    logger = logging.getLogger(__name__)
    config_path = _resolve_config_path(config_path)
    incoming_keys = sorted((config_data or {}).keys())
    logger.debug("保存配置请求: path=%s keys=%s", config_path, incoming_keys)

    with _config_lock:
        _config_write_in_progress = True
        try:
            existing_config = {}
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
                    logger.debug(f"读取现有配置: {len(existing_config)} 个顶层键")

            merged_config = deep_merge(existing_config, config_data)
            logger.debug(f"合并后配置: {len(merged_config)} 个顶层键")

            try:
                test_config = AppConfig(**merged_config)
                logger.debug("配置验证通过")
            except Exception as e:
                logger.error(f"配置验证失败: {e}")
                if _config:
                    current_dict = _config.model_dump()
                    merged_config = deep_merge(current_dict, config_data)
                    test_config = AppConfig(**merged_config)
                    logger.info("使用内存配置作为基础后验证通过")
                else:
                    raise

            next_mtime = _write_yaml_atomically(config_path, merged_config)
            _config = test_config
            _config_loaded_path = config_path
            _config_loaded_mtime = next_mtime
            _config_last_error = ""
            logger.debug(
                "配置已成功保存并原子更新: path=%s top_keys=%s updated_keys=%s",
                config_path,
                len(merged_config),
                incoming_keys,
            )
            return _config
        except Exception as e:
            _config_last_error = str(e)
            logger.error(f"保存配置失败: {e}")
            raise
        finally:
            _config_write_in_progress = False

def reload_config() -> AppConfig:
    """重新加载配置（用于配置变更后）"""
    global _config, _config_loaded_mtime, _config_loaded_path, _config_last_error, _config_reload_in_progress
    
    logger = logging.getLogger(__name__)
    config_path = _resolve_config_path()
    logger.info(f"[RELOAD] 重新加载配置文件：{config_path}")

    if not os.path.exists(config_path):
        logger.warning(f"[RELOAD] 配置文件不存在：{config_path}")
        return _config if _config else load_config()

    with _config_lock:
        _config_reload_in_progress = True
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f) or {}

            if 'classification' in config_data and config_data['classification']:
                validated_rules = []
                for rule_data in config_data['classification']:
                    try:
                        rule_data_cleaned = dict(rule_data)
                        if 'path_template' not in rule_data_cleaned or rule_data_cleaned['path_template'] is None:
                            rule_data_cleaned['path_template'] = ''
                        rule = ClassificationRule(**rule_data_cleaned)
                        validated_rules.append(rule)
                    except Exception as e:
                        logger.warning(f"分类规则加载失败: {rule_data}, 错误: {e}")
                if validated_rules:
                    config_data['classification'] = [r.model_dump() for r in validated_rules]

            if 'filter' in config_data and config_data['filter'] and 'rules' in config_data['filter'] and config_data['filter']['rules']:
                validated_filter_rules = []
                for rule_data in config_data['filter']['rules']:
                    try:
                        if 'target' not in rule_data or not rule_data['target']:
                            rule_data['target'] = 'file'
                        rule = FilterRule(**rule_data)
                        validated_filter_rules.append(rule)
                    except Exception as e:
                        logger.warning(f"过滤规则加载失败: {rule_data}, 错误: {e}")
                if validated_filter_rules:
                    config_data['filter']['rules'] = [r.model_dump() for r in validated_filter_rules]

            _config = AppConfig(**config_data)
            _config_loaded_path = config_path
            _config_loaded_mtime = os.path.getmtime(config_path) if os.path.exists(config_path) else 0.0
            _config_last_error = ""
            logger.info(f"[RELOAD] 配置重新加载成功")
            logger.info(f"[RELOAD] storage.input_path = {_config.storage.input_path}")
            logger.info(f"[RELOAD] rename.template = '{_config.rename.template}'")
        except Exception as e:
            _config_last_error = str(e)
            logger.error(f"[RELOAD] 配置重新加载失败：{e}", exc_info=True)
            if _config is None:
                _config = AppConfig()
        finally:
            _config_reload_in_progress = False

    return _config


def get_config_runtime_state() -> dict:
    return {
        "path": _config_loaded_path or _resolve_config_path(),
        "loaded_mtime": _config_loaded_mtime,
        "write_in_progress": _config_write_in_progress,
        "reload_in_progress": _config_reload_in_progress,
        "last_error": _config_last_error,
        "loaded": _config is not None,
    }


# ========== 配置文件热重载功能 ==========

# 全局变量存储配置文件路径和监控器
_config_file_path: Optional[str] = None
_config_observer: Optional[Observer] = None
_config_change_callbacks: list[Callable] = []
_config_lock = threading.Lock()


class ConfigFileChangeHandler(FileSystemEventHandler):
    """配置文件变更处理器"""
    
    def __init__(self):
        super().__init__()
        self._debounce_timer = None
        self._debounce_interval = 0.5  # 防抖间隔（秒）
    
    def on_modified(self, event):
        """文件修改事件处理"""
        if isinstance(event, FileModifiedEvent):
            # 防止重复触发，使用防抖
            if self._debounce_timer:
                self._debounce_timer.cancel()
            
            logger = logging.getLogger(__name__)
            logger.info(f"[CONFIG] 检测到配置文件修改：{event.src_path}")
            
            # 延迟执行，避免多次触发
            self._debounce_timer = threading.Timer(self._debounce_interval, self._on_modified_debounced)
            self._debounce_timer.start()
    
    def _on_modified_debounced(self):
        """防抖后的处理逻辑"""
        try:
            logger = logging.getLogger(__name__)
            logger.info("[CONFIG] 开始重新加载配置文件...")
            
            # 重新加载配置
            new_config = load_config(_config_file_path)
            
            # 通知所有回调函数
            for callback in _config_change_callbacks:
                try:
                    callback(new_config)
                except Exception as e:
                    logger.error(f"[CONFIG] 回调函数执行失败：{e}")
            
            logger.info("[CONFIG] 配置文件热重载完成")
        except Exception as e:
            logging.getLogger(__name__).error(f"[CONFIG] 热重载失败：{e}")


def register_config_change_callback(callback: Callable):
    """注册配置变更回调函数
    
    Args:
        callback: 回调函数，签名应为 func(new_config: AppConfig)
    """
    _config_change_callbacks.append(callback)
    logger = logging.getLogger(__name__)
    logger.info(f"[CONFIG] 注册配置变更回调，当前回调数：{len(_config_change_callbacks)}")


def unregister_config_change_callback(callback: Callable):
    """注销配置变更回调函数"""
    if callback in _config_change_callbacks:
        _config_change_callbacks.remove(callback)


def start_config_watcher(config_path: str = None):
    """启动配置文件监控器
    
    Args:
        config_path: 配置文件路径，如果不传则自动检测
    """
    global _config_file_path, _config_observer
    
    logger = logging.getLogger(__name__)
    
    # 确定配置文件路径
    if config_path is None:
        env_config_path = os.environ.get('CONFIG_PATH')
        if env_config_path:
            config_path = env_config_path
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
            config_path = os.path.join(project_root, 'data', 'config', 'config.yaml')
    
    config_path = os.path.abspath(config_path)
    _config_file_path = config_path
    
    logger.info(f"[CONFIG] 启动配置文件监控：{config_path}")
    
    # 检查文件是否存在
    if not os.path.exists(config_path):
        logger.warning(f"[CONFIG] 配置文件不存在，将在保存时创建：{config_path}")
        # 即使文件不存在也启动监控，等待文件创建
    
    # 创建监控器
    try:
        event_handler = ConfigFileChangeHandler()
        
        # 确保目录存在
        config_dir = os.path.dirname(config_path)
        os.makedirs(config_dir, exist_ok=True)
        
        _config_observer = Observer()
        _config_observer.schedule(event_handler, path=config_dir, recursive=False)
        _config_observer.start()
        
        logger.info("[CONFIG] 配置文件监控器已启动")
    except Exception as e:
        logger.error(f"[CONFIG] 启动配置文件监控器失败：{e}")


def stop_config_watcher():
    """停止配置文件监控器"""
    global _config_observer
    
    if _config_observer:
        _config_observer.stop()
        _config_observer.join()
        _config_observer = None
        logging.getLogger(__name__).info("[CONFIG] 配置文件监控器已停止")


def get_config_file_path() -> str:
    """获取配置文件路径"""
    return _config_file_path or os.environ.get('CONFIG_PATH', './data/config/config.yaml')
