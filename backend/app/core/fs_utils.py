"""文件系统通用工具：高效 move + 大 buffer 流式复制 + 进度回调。

历史背景
========
归档（``_archive_source_file``）和分类（``classifier._move_with_rename``）都用
``shutil.move``。当 source 和 dest 在不同文件系统 / 不同 Docker 卷 / NAS 挂载点时，
``shutil.move`` 退化为 ``copy2 + delete``，默认 buffer 较小，1.56 GB 文件
在 NAS / SMB / NFS 上能跑十几分钟，且没有任何进度回报，前端表现为 "归档压缩包 95%"
长时间不动。

本模块提供：
- :func:`move_path_efficient`：同卷直接 ``os.rename``；跨卷走 8 MB buffer 流式复制 + 删源。
- 复制过程中每 ``progress_throttle_bytes`` 字节回调一次进度，方便上层把
  "归档压缩包 60% (1.0GB / 1.56GB)" 实时上报给前端。
- 对单文件和目录两种情形都做覆盖。

不做的事情
==========
- 不引入第三方依赖（``aiofiles`` / ``rsync``），保持原有运行环境一致性。
- 不做并发文件复制：典型 ASMR 作品目录单文件较大（音轨 / mp3 / wav），
  并发收益有限，且容易把 NAS 网卡打满反而拖累整机。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# NAS / SMB / NFS 上 16 KB - 64 KB buffer 频繁 RPC 拖性能；8 MB 是常见甜点：
# 单次系统调用承担足够多数据，又不会在内存里堆压一个超大缓冲区。
LARGE_BUFFER = 8 * 1024 * 1024

# 进度回调节流：避免每次 8 MB 写入都触发回调（前端 update_progress 也会查询数据库）
DEFAULT_PROGRESS_THROTTLE = 4 * 1024 * 1024


ProgressCallback = Callable[[int, int], None]


async def move_path_efficient(
    src: str,
    dst: str,
    *,
    progress_cb: Optional[ProgressCallback] = None,
    buffer_size: int = LARGE_BUFFER,
    progress_throttle_bytes: int = DEFAULT_PROGRESS_THROTTLE,
) -> None:
    """跨设备友好的 move。

    - 同卷直接 ``os.rename``（瞬间完成）。
    - 跨卷走流式 copy + 删源。``progress_cb(copied_bytes, total_bytes)``
      在跨卷复制中每 ``progress_throttle_bytes`` 字节回调一次。
    - 失败抛出原始异常，上层应自行 retry / 记录日志。
    """
    src = str(src)
    dst = str(dst)

    # 同卷 fast path：直接 rename，不会产生任何 IO。
    try:
        await asyncio.to_thread(os.rename, src, dst)
        return
    except OSError as exc:
        # EXDEV（跨设备）/ PermissionError / 跨 NAS 等情况下退到流式 copy
        logger.debug(
            "os.rename 失败（%s），回退跨卷流式复制: %s -> %s",
            getattr(exc, "errno", "?"),
            src,
            dst,
        )

    if await asyncio.to_thread(os.path.isdir, src):
        await _copy_tree_buffered(
            src,
            dst,
            buffer_size=buffer_size,
            progress_cb=progress_cb,
            progress_throttle_bytes=progress_throttle_bytes,
        )
        await asyncio.to_thread(shutil.rmtree, src, ignore_errors=False)
    else:
        await _copy_file_buffered(
            src,
            dst,
            buffer_size=buffer_size,
            progress_cb=progress_cb,
            progress_throttle_bytes=progress_throttle_bytes,
        )
        await asyncio.to_thread(os.remove, src)


async def _copy_file_buffered(
    src: str,
    dst: str,
    *,
    buffer_size: int,
    progress_cb: Optional[ProgressCallback],
    progress_throttle_bytes: int,
) -> None:
    total = await asyncio.to_thread(_safe_size, src)
    state = {"copied": 0, "last_emit": 0}

    def _emit(force: bool = False) -> None:
        if not progress_cb:
            return
        if not force and (state["copied"] - state["last_emit"] < progress_throttle_bytes):
            return
        try:
            progress_cb(state["copied"], total)
        except Exception:
            logger.debug("progress_cb 回调异常已忽略", exc_info=True)
        state["last_emit"] = state["copied"]

    def _do_copy() -> None:
        with open(src, "rb", buffering=0) as fsrc, open(dst, "wb", buffering=0) as fdst:
            while True:
                chunk = fsrc.read(buffer_size)
                if not chunk:
                    break
                fdst.write(chunk)
                state["copied"] += len(chunk)
                _emit(force=False)

    await asyncio.to_thread(_do_copy)
    try:
        await asyncio.to_thread(shutil.copystat, src, dst)
    except Exception:
        # copystat 失败不影响数据正确性
        logger.debug("copystat 失败已忽略: %s -> %s", src, dst, exc_info=True)
    _emit(force=True)


async def _copy_tree_buffered(
    src: str,
    dst: str,
    *,
    buffer_size: int,
    progress_cb: Optional[ProgressCallback],
    progress_throttle_bytes: int,
) -> None:
    total = await asyncio.to_thread(_calc_dir_size, src)
    state = {"copied": 0, "last_emit": 0}

    def _emit(force: bool = False) -> None:
        if not progress_cb:
            return
        if not force and (state["copied"] - state["last_emit"] < progress_throttle_bytes):
            return
        try:
            progress_cb(state["copied"], total)
        except Exception:
            logger.debug("progress_cb 回调异常已忽略", exc_info=True)
        state["last_emit"] = state["copied"]

    def _do_copy_tree() -> None:
        for root, _, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target_dir = dst if rel == "." else os.path.join(dst, rel)
            os.makedirs(target_dir, exist_ok=True)
            for filename in files:
                s_file = os.path.join(root, filename)
                d_file = os.path.join(target_dir, filename)
                try:
                    with open(s_file, "rb", buffering=0) as fsrc, open(d_file, "wb", buffering=0) as fdst:
                        while True:
                            chunk = fsrc.read(buffer_size)
                            if not chunk:
                                break
                            fdst.write(chunk)
                            state["copied"] += len(chunk)
                            _emit(force=False)
                except Exception:
                    # 单文件失败抛出，由上层决定如何处理（清理 / 重试）。
                    raise
                try:
                    shutil.copystat(s_file, d_file)
                except Exception:
                    logger.debug("copystat 失败已忽略: %s", s_file, exc_info=True)

    await asyncio.to_thread(_do_copy_tree)
    _emit(force=True)


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _calc_dir_size(path: str) -> int:
    total = 0
    try:
        for root, _, files in os.walk(path):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        return 0
    return total
