"""统一文件搬运入口：原生重命名、宿主克隆、独占暂存及可恢复清源。"""
from __future__ import annotations

import os
from typing import Callable, Optional


# NAS / SMB / NFS 上 16 KB - 64 KB buffer 频繁 RPC 拖性能；8 MB 是常见甜点：
# 单次系统调用承担足够多数据，又不会在内存里堆压一个超大缓冲区。
LARGE_BUFFER = 8 * 1024 * 1024

# 进度回调节流：避免每次 8 MB 写入都触发回调（前端 update_progress 也会查询数据库）
DEFAULT_PROGRESS_THROTTLE = 4 * 1024 * 1024


ProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]


async def move_path_efficient(
    src: str,
    dst: str,
    *,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[CancellationCheck] = None,
    buffer_size: int = LARGE_BUFFER,
    progress_throttle_bytes: int = DEFAULT_PROGRESS_THROTTLE,
    overwrite: bool = False,
    phase_cb=None,
) -> None:
    """异步移动；取消后等待实际文件操作停止，再将取消返回业务层。"""
    from .staged_file_move import move_path_async
    await move_path_async(
        src, dst, progress_cb=progress_cb, cancel_check=cancel_check,
        buffer_size=buffer_size, progress_throttle_bytes=progress_throttle_bytes,
        overwrite=overwrite, phase_cb=phase_cb,
    )


# 同步业务和需要自行提交的事务共用相同的副本生成逻辑。
from .staged_file_move import (
    MoveCleanupPending, copy_file_publish_sync, copy_path_exclusive_sync,
    move_path_sync, move_path_replacing_sync, publish_path,
    run_file_operation_async,
)
