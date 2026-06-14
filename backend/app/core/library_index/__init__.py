"""库存搜索索引模块（library_index）。

背景：
    项目里有两类高频业务需要在文件系统里"找 RJ 号路径 / 算目录大小"：
    - rj_subtitle_service / task_engine 的 RJ 号定位
    - library_manager 的大小统计、远程搜索、删除预审
    在群晖这种几十万级目录的环境下，os.walk 与 SYNO.FileStation.Search
    都会造成显著卡顿。本模块抽出独立的 LibraryIndexService，在 PostgreSQL
    里常驻一份"库存 → 条目"快照，所有搜索 / 统计走 SQL 查询（ms 级）。

分层：
    types.py           —— IndexEntry / IndexStatus / WatcherEvent 值对象
    _helpers.py        —— RJ 正则 + 跳过规则共享（local + remote 都用）
    snapshot_store.py  —— PostgreSQL CRUD（library_index_entries + library_index_status）
    local_scanner.py   —— 本地 os.scandir 全量扫
    remote_scanner.py  —— 远程 SYNO.FileStation.Search 全量抓
    watcher_driver.py  —— [批次 4] WatcherDriver 抽象 + watchdog/polling/remote
    service.py         —— LibraryIndexService 对外唯一入口

当前进度：批次 3。
- 已交付：SnapshotStore + LocalScanner + RemoteScanner + LibraryIndexService
- API：/api/library/index/{rebuild,status,search}，rebuild 同时支持
  local 与 synology_filestation 两种库存类型
- self_mutation 接口（业务自身写操作主动通知索引）
- 批次 4 才上 watcher_driver；当前外部变更需要手动重建或周期重建
"""

from .local_scanner import LocalScanner
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

__all__ = [
    'EntryType',
    'IndexEntry',
    'IndexStatus',
    'IndexStatusName',
    'LibraryIndexService',
    'LocalScanner',
    'RemoteScanner',
    'SnapshotStore',
    'WatcherEvent',
    'WatcherEventKind',
    'WatcherMode',
    'get_library_index_service',
    'get_snapshot_store',
]
