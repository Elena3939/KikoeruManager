"""库存搜索索引模块（library_index）。

背景：
    项目里有两类高频业务需要在文件系统里"找 RJ 号路径 / 算目录大小"：
    - rj_subtitle_service / task_engine 的 RJ 号定位
    - library_manager 的本地大小统计、本地搜索、删除预审
    本模块抽出独立的 LibraryIndexService，在 PostgreSQL 里常驻一份
    "库存 → 条目"快照。本地库存用 SQL 查询（ms 级），群晖远程库存
    不再创建该快照，统一走 FileStation 原生浏览 / 搜索。

分层：
    types.py           —— IndexEntry / IndexStatus / WatcherEvent 值对象
    _helpers.py        —— RJ 正则 + 跳过规则共享（local + remote 都用）
    snapshot_store.py  —— PostgreSQL CRUD（library_index_entries + library_index_status）
    local_scanner.py   —— 本地 os.scandir 全量扫
    remote_scanner.py  —— 旧远程快照扫描器；入口已禁用，仅为兼容保留
    watcher_driver.py  —— [批次 4] WatcherDriver 抽象 + watchdog/polling/remote
    service.py         —— LibraryIndexService 对外唯一入口

当前进度：本地库存索引生效，远程库存索引停用。
- 已交付：SnapshotStore + LocalScanner + LibraryIndexService
- API：/api/library/index/{rebuild,status,search} 仅支持 local 库存；
  synology_filestation 状态返回 disabled，不触发重建
- self_mutation 接口（业务自身写操作主动通知索引）
- 批次 4 才上 watcher_driver；当前外部变更需要手动重建或周期重建
"""

from .local_scanner import LocalScanner
from .mutation_service import (
    LibraryIndexMutationService,
    get_library_index_mutation_service,
    start_library_index_mutation_service,
    stop_library_index_mutation_service,
)
from .remote_scanner import RemoteScanner
from .service import LibraryIndexService, get_library_index_service
from .snapshot_store import SnapshotStore, get_snapshot_store
from .types import (
    EntryType,
    IndexEntry,
    IndexStatus,
    IndexStatusName,
    WatcherEvent,
    WatcherEventKind,
    WatcherMode,
)
from .watcher_driver import (
    get_library_index_watcher_driver,
    start_library_index_watcher_driver,
    stop_library_index_watcher_driver,
)

__all__ = [
    'EntryType',
    'IndexEntry',
    'IndexStatus',
    'IndexStatusName',
    'LibraryIndexService',
    'LibraryIndexMutationService',
    'LocalScanner',
    'RemoteScanner',
    'SnapshotStore',
    'WatcherEvent',
    'WatcherEventKind',
    'WatcherMode',
    'get_library_index_service',
    'get_library_index_mutation_service',
    'get_library_index_watcher_driver',
    'get_snapshot_store',
    'start_library_index_mutation_service',
    'start_library_index_watcher_driver',
    'stop_library_index_mutation_service',
    'stop_library_index_watcher_driver',
]
