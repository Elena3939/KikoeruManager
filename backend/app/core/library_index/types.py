"""library_index 模块内部使用的值对象。

纯 dataclass，不依赖 SQLAlchemy，方便在 scanner / watcher /
service 层之间传递事件，而不用打开 ORM session。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

EntryType = Literal['dir', 'file']
IndexStatusName = Literal['idle', 'syncing', 'ready', 'error', 'disabled']
WatcherMode = Literal['watchdog', 'polling', 'remote_rescan', 'disabled']
WatcherEventKind = Literal['created', 'modified', 'deleted', 'moved']


@dataclass(slots=True)
class IndexEntry:
    """索引里一条文件或目录记录。

    - relative_path：相对 library.root_path 的 posix 字符串（如 "社团A/RJ01234567"）
    - absolute_path：
        - local 库存：完整 fs 路径（Windows 可能含反斜杠）
        - synology_filestation 库存：群晖 posix 路径（如 /volume1/asmr/...）
    - size：文件存自身字节数；目录存递归大小，避免运行时 os.walk
    - file_count：目录才有意义（目录下文件总数），文件条目统一为 0
    - mtime：毫秒级 Unix 时间戳
    - depth：从库根起的层级（根自身是 0）
    """
    library_id: str
    entry_type: EntryType
    relative_path: str
    absolute_path: str
    name: str
    rjcode: Optional[str] = None
    parent_path: Optional[str] = None
    size: int = 0
    file_count: int = 0
    mtime: Optional[int] = None
    depth: Optional[int] = None
    indexed_at: int = 0
    generation: int = 1
    materialized_seq: int = 0


@dataclass(slots=True)
class IndexStatus:
    """某个库存的索引整体状态。"""
    library_id: str
    status: IndexStatusName = 'idle'
    watcher_mode: Optional[WatcherMode] = None
    last_full_scan_at: Optional[int] = None
    last_event_at: Optional[int] = None
    total_entries: int = 0
    total_size_bytes: int = 0
    folder_count: int = 0
    error: Optional[str] = None
    updated_at: int = 0
    accepted_seq: int = 0
    materialized_seq: int = 0
    state_revision: int = 0
    view_revision: int = 0
    active_generation: int = 1
    building_generation: Optional[int] = None
    catchup_state: str = 'idle'
    last_operation_id: Optional[str] = None
    materializer_owner: Optional[str] = None
    materializer_lease_until: Optional[str] = None
    materializer_epoch: int = 0
    blocked_seq: Optional[int] = None
    catchup_error: Optional[str] = None

    @property
    def pending_events(self) -> int:
        return max(int(self.accepted_seq or 0) - int(self.materialized_seq or 0), 0)


@dataclass(slots=True)
class WatcherEvent:
    """watcher 实时事件。由 WatcherDriver 派发给 SnapshotStore / Service。

    kind 语义：
    - created：新增文件或目录
    - modified：内容变化（文件）或直接子项发生变化（目录）
    - deleted：删除
    - moved：重命名或跨目录移动；old_absolute_path 为旧路径
    """
    library_id: str
    kind: WatcherEventKind
    absolute_path: str
    is_directory: bool = False
    old_absolute_path: Optional[str] = None
