"""LocalScanner：纯本地文件系统的全量扫描器。

用 os.scandir() 替代 os.walk()，少做一次 stat 调用；按"后序"yield：
先文件、再子目录递归结果、最后当前目录自身，让父目录的
size / file_count 在 yield 时一次性从子项汇总好，避免后续二次回扫。

输出 IndexEntry，由 SnapshotStore 落库。本模块不直接读写 DB，
也不依赖 LibraryManager / settings；上层 Service 负责把 LibraryDefinition
解析成 (library_id, root_path) 再调本类。

跳过规则与 RJ 提取规则集中在 _helpers.py 里，与 RemoteScanner / WatcherDriver
共享，避免在多个 scanner 里维护多份正则。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Iterator, Optional

from ._helpers import extract_rjcode as _extract_rjcode
from ._helpers import should_skip_name as _should_skip
from .types import IndexEntry

logger = logging.getLogger(__name__)


def _to_relative_posix(absolute_path: str, root_path: str) -> str:
    """计算相对路径并强制为 posix 风格。

    根目录返回 ''；跨盘符（Windows）返回 ''（不应发生，scanner 永远在根下）。
    """
    try:
        rel = os.path.relpath(absolute_path, root_path)
    except ValueError:
        return ""
    if rel in {".", ""}:
        return ""
    return rel.replace(os.sep, "/")


class LocalScanner:
    """单库存全量扫描器。

    参数：
    - max_depth：限制递归深度，None 不限。一般给 None 即可。
    - progress_callback：每扫到 progress_interval 个文件回调一次，接收已扫文件数
    - progress_interval：进度回调粒度，默认 5000 文件
    """

    def __init__(
        self,
        *,
        max_depth: Optional[int] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        progress_interval: int = 5000,
    ):
        self.max_depth = max_depth
        self.progress_callback = progress_callback
        self.progress_interval = max(progress_interval, 1)

    def scan(self, library_id: str, root_path: str) -> Iterator[IndexEntry]:
        """扫描整个库存，按后序 yield IndexEntry（含根条目）。

        异常处理：
        - 根路径不存在：抛 FileNotFoundError
        - 根路径不是目录：抛 NotADirectoryError
        - 子目录读失败（权限 / IO 错误）：写日志后跳过
        """
        if not root_path:
            raise FileNotFoundError("root_path 为空")
        if not os.path.exists(root_path):
            raise FileNotFoundError(f"库存根目录不存在: {root_path}")
        if not os.path.isdir(root_path):
            raise NotADirectoryError(f"库存根路径不是目录: {root_path}")

        normalized_root = os.path.abspath(root_path)
        scanned = [0]  # 用 list 模拟可变闭包计数器
        started = time.time()

        try:
            yield from self._walk(
                library_id=library_id,
                current_path=normalized_root,
                root_path=normalized_root,
                depth=0,
                scanned=scanned,
            )
        finally:
            elapsed = time.time() - started
            logger.info(
                "[LocalScanner] 扫描完成 library=%s root=%s files=%s elapsed=%.2fs",
                library_id, normalized_root, scanned[0], elapsed,
            )

    def scan_subtree(
        self,
        library_id: str,
        library_root: str,
        subtree_path: str,
    ) -> Iterator[IndexEntry]:
        """扫子树（含子树自身），relative_path / depth 始终基于 library_root 计算。

        给业务自身写操作（解压入库 / rename / 字幕落盘 / 冲突重绑等）调用，
        把刚刚创建好的子树立即 upsert 到索引，避免依赖全量重建。

        异常：
        - library_root / subtree_path 为空 / 不存在 / 不是目录：抛 FileNotFoundError
        - subtree 不在 library_root 下：抛 ValueError
        - 子目录读失败：和 scan() 一致，日志后跳过
        """
        if not library_root:
            raise FileNotFoundError("library_root 为空")
        if not subtree_path:
            raise FileNotFoundError("subtree_path 为空")
        normalized_root = os.path.abspath(library_root)
        normalized_subtree = os.path.abspath(subtree_path)
        if not os.path.exists(normalized_subtree):
            raise FileNotFoundError(f"子树路径不存在: {subtree_path}")
        if not os.path.isdir(normalized_subtree):
            raise NotADirectoryError(f"子树路径不是目录: {subtree_path}")

        # 越界保护：子树必须在 library_root 下，否则 relative_path 会变成 ../
        # 触发 SnapshotStore 写入异常路径。这里直接拦掉，调用方 catch 后静默。
        if normalized_subtree != normalized_root:
            try:
                rel_check = os.path.relpath(normalized_subtree, normalized_root)
            except ValueError as exc:
                raise ValueError(
                    f"subtree 不在 library_root 下（跨盘符）: {subtree_path}"
                ) from exc
            if rel_check.startswith("..") or rel_check in {".", ""}:
                raise ValueError(
                    f"subtree 不在 library_root 下: subtree={subtree_path} "
                    f"library_root={library_root}"
                )

        scanned = [0]
        started = time.time()
        # 子树的 depth：相对 library_root 计算
        if normalized_subtree == normalized_root:
            subtree_depth = 0
        else:
            rel = os.path.relpath(normalized_subtree, normalized_root)
            subtree_depth = rel.count(os.sep) + 1

        try:
            yield from self._walk(
                library_id=library_id,
                current_path=normalized_subtree,
                root_path=normalized_root,
                depth=subtree_depth,
                scanned=scanned,
            )
        finally:
            elapsed = time.time() - started
            logger.info(
                "[LocalScanner] 子树扫描完成 library=%s subtree=%s files=%s elapsed=%.2fs",
                library_id, normalized_subtree, scanned[0], elapsed,
            )

    def _walk(
        self,
        *,
        library_id: str,
        current_path: str,
        root_path: str,
        depth: int,
        scanned: list[int],
    ) -> Iterator[IndexEntry]:
        # 后序遍历：先 yield 文件，再递归 yield 子目录的结果，最后 yield 当前目录
        is_root = (current_path == root_path)
        total_size = 0
        file_count = 0
        children_dirs: list[str] = []

        # 1) 列当前目录直接子项；区分文件 / 子目录
        try:
            iterator = os.scandir(current_path)
        except OSError as exc:
            logger.warning("[LocalScanner] 扫描目录失败 path=%s err=%s", current_path, exc)
            iterator = None

        if iterator is not None:
            try:
                with iterator:
                    for entry in iterator:
                        try:
                            name = entry.name
                            if _should_skip(name):
                                continue

                            child_absolute = entry.path
                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                            except OSError as exc:
                                logger.debug("[LocalScanner] is_dir 失败 path=%s err=%s",
                                             child_absolute, exc)
                                continue

                            if is_dir:
                                if self.max_depth is not None and depth + 1 > self.max_depth:
                                    continue
                                children_dirs.append(child_absolute)
                                # 递归在第二轮统一处理；这里只暂存路径
                                continue

                            # 文件分支：直接 yield
                            try:
                                stat_result = entry.stat(follow_symlinks=False)
                            except OSError as exc:
                                logger.debug("[LocalScanner] stat 失败 path=%s err=%s",
                                             child_absolute, exc)
                                continue

                            size = int(stat_result.st_size or 0)
                            mtime_ms = int(stat_result.st_mtime * 1000)
                            relative = _to_relative_posix(child_absolute, root_path)
                            parent_rel = _to_relative_posix(current_path, root_path)

                            yield IndexEntry(
                                library_id=library_id,
                                entry_type='file',
                                relative_path=relative,
                                absolute_path=child_absolute,
                                name=name,
                                rjcode=_extract_rjcode(name),
                                parent_path=parent_rel,
                                size=size,
                                file_count=0,
                                mtime=mtime_ms,
                                depth=depth + 1,
                            )

                            total_size += size
                            file_count += 1
                            scanned[0] += 1
                            if (
                                self.progress_callback
                                and scanned[0] % self.progress_interval == 0
                            ):
                                try:
                                    self.progress_callback(scanned[0])
                                except Exception:
                                    logger.debug(
                                        "[LocalScanner] progress_callback 抛异常",
                                        exc_info=True,
                                    )
                        except OSError as exc:
                            logger.debug("[LocalScanner] 处理 entry 失败 path=%s err=%s",
                                         current_path, exc)
                            continue
            except OSError as exc:
                logger.warning("[LocalScanner] 迭代目录失败 path=%s err=%s",
                               current_path, exc)

        # 2) 递归扫每个子目录；用 dict 暂存子目录自身的 size / file_count
        for sub_path in children_dirs:
            sub_size = 0
            sub_file_count = 0
            for sub_entry in self._walk(
                library_id=library_id,
                current_path=sub_path,
                root_path=root_path,
                depth=depth + 1,
                scanned=scanned,
            ):
                # 子目录"自身"那条用绝对路径匹配；它一定是该子树最后 yield 的那条
                if (
                    sub_entry.entry_type == 'dir'
                    and sub_entry.absolute_path == sub_path
                ):
                    sub_size = sub_entry.size
                    sub_file_count = sub_entry.file_count
                yield sub_entry

            total_size += sub_size
            file_count += sub_file_count

        # 3) yield 当前目录自身
        try:
            stat_result = os.stat(current_path)
            mtime_ms: Optional[int] = int(stat_result.st_mtime * 1000)
        except OSError:
            mtime_ms = None

        relative_self = _to_relative_posix(current_path, root_path)
        if is_root:
            current_name = os.path.basename(current_path) or current_path
            parent_for_self: Optional[str] = None
            current_depth = 0
        else:
            current_name = os.path.basename(current_path)
            parent_for_self = _to_relative_posix(os.path.dirname(current_path), root_path)
            current_depth = depth

        yield IndexEntry(
            library_id=library_id,
            entry_type='dir',
            relative_path=relative_self,
            absolute_path=current_path,
            name=current_name,
            rjcode=_extract_rjcode(current_name),
            parent_path=parent_for_self,
            size=total_size,
            file_count=file_count,
            mtime=mtime_ms,
            depth=current_depth,
        )
