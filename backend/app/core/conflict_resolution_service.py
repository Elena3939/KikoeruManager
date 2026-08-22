import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from ..config.settings import get_config
from ..core.extract_service import ExtractService
from ..core.filter_service import FilterService
from ..core.folder_compare_service import get_folder_compare_service
from ..core.library_manager import get_library_manager
from ..core.resource_budget_service import get_resource_budget_service
from ..core.task_engine import Task, TaskType

logger = logging.getLogger(__name__)


async def _noop_stats() -> Optional[dict[str, Any]]:
    """asyncio.gather 的占位 awaitable：不需要计算 stats 时返回 None，避免分支写两套 gather。"""
    return None


@dataclass
class ConflictMergeSession:
    id: str
    conflict_id: str
    workspace: str
    staged_root: str       # 已暂存时：临时目录；懒暂存时：原始源目录路径
    existing_path: str
    existing_library_id: Optional[str]
    existing_library_type: str
    compare_items: list[dict[str, Any]]
    created_at: float
    source_is_staged: bool = False  # True=已复制到 workspace；False=使用原始源路径


@dataclass
class MergePreviewJob:
    """合并预览异步任务句柄：解决"大压缩包必 504"问题。

    用户点合并 → 后端立即创建 job + asyncio.create_task 启动 worker → HTTP 立即返回 job_id；
    前端轮询 GET /api/conflicts/{id}/preview-job/{job_id} 拿真实阶段 / 百分比 / message；
    worker 完成时 status='completed' + result=preview，失败时 status='failed' + error。

    `stage` 与 `stage_label`：
      - `init` 初始化 → `resolve_path` 定位来源 → `copy_archive` 复制压缩包
      - `extract` 解压新包（monitor 持续从 extract_task.progress 拿真实 7z 百分比 + step）
      - `nested_extract` 嵌套解压（extract_task.current_step 含"嵌套"时切换）
      - `filter` 过滤临时目录 → `scan_existing` 扫描库存 → `compare` 生成差异树
      - `done` 完成 / `failed` 失败
    """
    id: str
    conflict_id: str
    status: str = "running"        # running | completed | failed
    stage: str = "init"
    stage_label: str = "初始化"
    message: str = ""
    percent: int = 0
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0


class ConflictResolutionService:
    def __init__(self) -> None:
        self._merge_sessions: dict[str, ConflictMergeSession] = {}
        # 合并预览异步 job 池 + 对应的 asyncio worker 句柄。
        # cleanup_old_merge_preview_jobs 定期回收超时 job，避免内存泄漏。
        self._merge_preview_jobs: dict[str, MergePreviewJob] = {}
        self._merge_preview_workers: dict[str, asyncio.Task] = {}

    def normalize_action(self, action: str) -> str:
        normalized = str(action or "").strip().upper()
        if normalized == "KEEP_OLD":
            return "SKIP"
        if normalized in {"KEEP_BOTH", "MERGE_LANG"}:
            return "MERGE"
        if normalized not in {"KEEP_NEW", "MERGE", "SKIP", "RETRY", "RENAME_VOLUMES", "CANCEL"}:
            raise ValueError("Unsupported conflict action")
        return normalized

    def _iter_libraries(self):
        manager = get_library_manager()
        config = manager.load_config()
        return manager._active_libraries(config)

    def infer_library_context(self, path: Optional[str], preferred_library_id: Optional[str] = None) -> dict[str, Any]:
        manager = get_library_manager()
        raw_path = str(path or "").strip()
        if not raw_path:
            return {
                "library_id": None,
                "library_type": "local",
                "library_name": "",
                "path": "",
                "is_remote": False,
            }

        libraries = list(self._iter_libraries())
        if preferred_library_id:
            libraries.sort(key=lambda library: 0 if library.id == preferred_library_id else 1)

        for library in libraries:
            if library.type == "synology_filestation":
                normalized_path = manager._normalize_remote_path(raw_path)
                browse_root = manager._normalize_remote_path(library.browse_root_path or library.root_path or "/")
                if manager._remote_path_is_within_root(normalized_path, browse_root):
                    return {
                        "library_id": library.id,
                        "library_type": library.type,
                        "library_name": library.name,
                        "path": normalized_path,
                        "is_remote": True,
                    }
                continue

            target_path = os.path.abspath(raw_path)
            browse_root = os.path.abspath(library.browse_root_path or library.root_path)
            if target_path == browse_root or target_path.startswith(browse_root + os.sep):
                return {
                    "library_id": library.id,
                    "library_type": library.type,
                    "library_name": library.name,
                    "path": target_path,
                    "is_remote": False,
                }

        if preferred_library_id:
            for library in (self._iter_libraries()):
                if library.id != preferred_library_id:
                    continue
                if library.type == "synology_filestation":
                    normalized_path = manager._normalize_remote_path(raw_path)
                    return {
                        "library_id": library.id,
                        "library_type": library.type,
                        "library_name": library.name,
                        "path": normalized_path,
                        "is_remote": True,
                    }
                break

        # 兜底分支：路径不在任何已配置库存内，按本地处理。
        # 旧实现把 raw_path.startswith("/") 当作远程信号，会把 docker 容器内的
        # /input1/RJ01393915.zip 这类容器内本地路径误判为远程，导致 _resolve_stats
        # 走 _describe_remote_path_stats(library_id=None) 直接返回 missing，
        # 前端"压缩包大小 / 创建时间"永远显示 "-"。
        return {
            "library_id": None,
            "library_type": "local",
            "library_name": "",
            "path": raw_path,
            "is_remote": False,
        }

    # 单次本地目录 stat 的硬上限：
    # - 群晖 / Docker / 网络挂载下 os.walk 单文件 stat 可能 5~50ms；
    # - 6 个 conflict × 2 路径 × 上千文件 → 60s 直接打死前端。
    # 这里给一个软超时 + 文件数兜底，超过即返回当前累计值并标记 truncated，
    # 让 UI 至少能把列表渲染出来，不要让一个超大目录把整个接口锁死。
    _LOCAL_STAT_MAX_FILES = 5000
    _LOCAL_STAT_MAX_SECONDS = 4.0

    def _describe_local_path_stats(self, path: Optional[str]) -> dict[str, Any]:
        target_path = str(path or "").strip()
        if not target_path:
            return {
                "exists": False,
                "kind": "missing",
                "size": None,
                "created_at": None,
                "modified_at": None,
                "file_count": None,
                "folder_count": None,
            }

        if not os.path.exists(target_path):
            return {
                "exists": False,
                "kind": "missing",
                "size": None,
                "created_at": None,
                "modified_at": None,
                "file_count": None,
                "folder_count": None,
            }

        try:
            stat = os.stat(target_path)
            created_at = stat.st_ctime
            modified_at = stat.st_mtime
        except OSError:
            created_at = None
            modified_at = None

        if os.path.isfile(target_path):
            try:
                size = os.path.getsize(target_path)
            except OSError:
                size = None
            return {
                "exists": True,
                "kind": "file",
                "size": size,
                "created_at": created_at,
                "modified_at": modified_at,
                "file_count": 1,
                "folder_count": 0,
            }

        total_size = 0
        file_count = 0
        folder_count = 1
        truncated = False
        deadline = time.monotonic() + self._LOCAL_STAT_MAX_SECONDS
        for root, dirs, files in os.walk(target_path):
            folder_count += len(dirs)
            file_count += len(files)
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except OSError:
                    continue
            if file_count >= self._LOCAL_STAT_MAX_FILES or time.monotonic() >= deadline:
                truncated = True
                logger.info(
                    "本地目录扫描触发上限保护，提前返回累计值: path=%s files=%s deadline_exceeded=%s",
                    target_path,
                    file_count,
                    time.monotonic() >= deadline,
                )
                break

        return {
            "exists": True,
            "kind": "folder",
            "size": total_size,
            "created_at": created_at,
            "modified_at": modified_at,
            "file_count": file_count,
            "folder_count": folder_count,
            "truncated": truncated,
        }

    async def _describe_remote_path_stats(
        self,
        library_id: Optional[str],
        path: Optional[str],
    ) -> dict[str, Any]:
        missing = {
            "exists": False,
            "kind": "missing",
            "size": None,
            "created_at": None,
            "modified_at": None,
            "file_count": None,
            "folder_count": None,
        }
        normalized_path = str(path or "").strip()
        if not library_id or not normalized_path:
            return dict(missing)

        manager = get_library_manager()
        library = next(
            (lib for lib in self._iter_libraries() if lib.id == library_id),
            None,
        )
        if not library or library.type != "synology_filestation" or not library.synology:
            return dict(missing)

        client = manager.get_cached_synology_client(library.synology)
        try:
            info = await client.stat(manager._normalize_remote_path(normalized_path))
            item = manager._first_remote_info_item(info) or {}
            if not item:
                return dict(missing)

            additional = item.get("additional", {}) or {}
            timestamps = additional.get("time", {}) or {}
            is_directory = bool(item.get("isdir"))
            modified_ts = timestamps.get("mtime")

            if is_directory:
                # 列表加载时不阻塞等待群晖 dir_size 计算：
                # 命中缓存就直接拿真实大小，没命中就触发后台刷新，本次返回 size=None。
                cached_size, status = manager._get_remote_cached_size(
                    normalized_path, modified_ts, True,
                )
                if cached_size is None or status != "ready":
                    try:
                        manager._ensure_remote_size_task(library, normalized_path, modified_ts)
                    except Exception:
                        logger.debug("触发远程目录大小后台刷新失败 path=%s", normalized_path, exc_info=True)
                size_value: Optional[int] = int(cached_size) if cached_size is not None else None
            else:
                raw_size = additional.get("size") or item.get("size") or 0
                try:
                    size_value = int(raw_size)
                except (TypeError, ValueError):
                    size_value = None

            return {
                "exists": True,
                "kind": "folder" if is_directory else "file",
                "size": size_value,
                "created_at": timestamps.get("crtime") or timestamps.get("ctime"),
                "modified_at": modified_ts,
                "file_count": None,
                "folder_count": None,
            }
        except Exception as exc:
            logger.warning("读取远程冲突路径统计失败 path=%s error=%s", normalized_path, exc)
            return dict(missing)

    async def _load_existing_remote_items(self, existing: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
        manager = get_library_manager()
        raw_path = str(existing.get("path") or "").strip()
        if not raw_path:
            return None

        candidates = self._remote_path_candidates(raw_path)
        preferred_library_id = existing.get("library_id") if existing.get("is_remote") else None
        libraries = list(self._iter_libraries())
        if preferred_library_id:
            libraries.sort(key=lambda lib: 0 if lib.id == preferred_library_id else 1)

        for lib in libraries:
            if lib.type != "synology_filestation":
                continue
            for candidate in candidates:
                try:
                    tree = await manager.folder_contents(lib.id, candidate)
                    existing["library_id"] = lib.id
                    existing["library_type"] = lib.type
                    existing["library_name"] = lib.name
                    existing["path"] = candidate
                    existing["is_remote"] = True
                    return tree.get("items") or []
                except Exception as exc:
                    logger.debug("群晖库存 %s 无法访问路径 %s: %s", lib.id, candidate, exc)
                    continue

        return None

    def _remote_path_candidates(self, path: str) -> list[str]:
        manager = get_library_manager()
        raw_path = str(path or "").strip()
        candidates: list[str] = []

        def add(value: Any) -> None:
            text = unquote(str(value or "").strip())
            if not text:
                return
            if text.startswith("path="):
                text = text.split("=", 1)[1]
            normalized = manager._normalize_remote_path(text)
            if normalized not in candidates:
                candidates.append(normalized)

        add(raw_path)
        parsed = urlparse(raw_path)
        if parsed.scheme and parsed.netloc:
            query = parse_qs(parsed.query)
            for launch_param in query.get("launchParam") or []:
                launch_query = parse_qs(unquote(launch_param))
                for value in launch_query.get("path") or []:
                    add(value)
                add(launch_param)
            for value in query.get("path") or []:
                add(value)
            if parsed.path and not parsed.path.startswith("/webapi/"):
                add(parsed.path)

        return candidates

    # ---------- conflict 路径修复 + stats 缓存 helpers ----------
    #
    # 历史 bug：classifier.py 解压后发现重复时，先用 /temp/RJxxx_subtask/... 写
    # conflict 记录，再把这个临时目录搬到 {library_path}/_conflicts/。导致 DB 里
    # conflict.new_path 永远指向已经不存在的临时路径，用户点合并/保留新版预览
    # 就 404 New source does not exist。
    #
    # 写入端 (classifier.py) 已经修成"先搬迁再写记录"。但 DB 里的老数据还得兜底：
    # _resolve_conflict_new_path 在 new_path 不存在时尝试 _conflicts/{basename} 备用路径，
    # 命中后通过 _maybe_persist_resolved_new_path 异步回写真实路径。
    #
    # 同时为了避免列表页每次刷新都对每条 conflict 重跑 os.walk 算大小，把 stats
    # 持久化到 conflict.new_metadata.{side}_stats_cache，按 (path, mtime) 失效。
    def _resolve_conflict_new_path(self, conflict) -> str:
        """优先返回 conflict.new_path；不存在则按多级 fallback 兜底找回数据。

        fallback 顺序（越靠前越优先 / 越精确）：
          1. `{library}/_conflicts/{basename}` —— 写入端旧 bug 留下的搬迁路径
          2. `{library}/_conflicts/{rjcode}` —— 按 RJ 号直接命名的子目录
          3. `{library}/_conflicts/*{rjcode}*` —— RJ 号模糊匹配（覆盖带后缀 / 时间戳的命名）
          4. 都不命中则原样返回 candidate，后续 raise 友好错误。
        """
        candidate = str(getattr(conflict, "new_path", "") or "").strip()
        if candidate and os.path.exists(candidate):
            return candidate
        try:
            library_path = str(getattr(get_config().storage, "library_path", "") or "").strip()
        except Exception:
            return candidate
        if not library_path:
            return candidate
        conflicts_dir = os.path.join(library_path, "_conflicts")
        # 1. _conflicts/{basename}
        basename = os.path.basename(candidate) if candidate else ""
        if basename:
            p1 = os.path.join(conflicts_dir, basename)
            if os.path.exists(p1):
                return p1
        # 2. _conflicts/{rjcode}
        rjcode = str(getattr(conflict, "rjcode", "") or "").strip()
        if rjcode:
            p2 = os.path.join(conflicts_dir, rjcode)
            if os.path.exists(p2):
                return p2
            # 3. _conflicts 下含 rjcode 的子项模糊匹配（命名可能带后缀 / 时间戳）
            try:
                if os.path.isdir(conflicts_dir):
                    for entry in os.listdir(conflicts_dir):
                        if rjcode in entry:
                            p3 = os.path.join(conflicts_dir, entry)
                            if os.path.exists(p3):
                                return p3
            except OSError:
                pass
        return candidate

    def _new_source_missing_error(self, conflict) -> FileNotFoundError:
        """拼装"新版本来源不存在"的友好错误：暴露 RJ / 原路径 / 尝试过的候选路径。

        前端拿到 detail 后会直接 toast，纯英文 "New source does not exist" 等于
        让用户摸瞎，这里中文化 + 列出所有兜底尝试过的路径方便定位。
        """
        original = str(getattr(conflict, "new_path", "") or "").strip()
        rjcode = str(getattr(conflict, "rjcode", "") or "").strip()
        tried: list[str] = []
        if original:
            tried.append(original)
        try:
            library_path = str(getattr(get_config().storage, "library_path", "") or "").strip()
        except Exception:
            library_path = ""
        if library_path:
            conflicts_dir = os.path.join(library_path, "_conflicts")
            basename = os.path.basename(original) if original else ""
            if basename:
                tried.append(os.path.join(conflicts_dir, basename))
            if rjcode:
                tried.append(os.path.join(conflicts_dir, rjcode))
                tried.append(f"{conflicts_dir}{os.sep}*{rjcode}*")
        rj_label = f"RJ{rjcode}" if rjcode and not rjcode.upper().startswith("RJ") else (rjcode or "未知 RJ")
        msg = (
            f"新版本来源路径不存在（{rj_label}）。原路径：{original or '(空)'}。"
            f"已尝试 fallback：{', '.join(tried) if tried else '(无)'}。"
            "该问题作品的新版本数据可能已被清理 / 搬迁，建议跳过该项以清理记录。"
        )
        return FileNotFoundError(msg)

    def _maybe_persist_resolved_new_path(
        self, conflict_id: str, original_path: str, resolved_path: str,
    ) -> None:
        if not conflict_id or not resolved_path:
            return
        if resolved_path == original_path:
            return
        try:
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                row = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
                if not row or str(row.new_path or "") != original_path:
                    return
                row.new_path = resolved_path
                metadata = dict(row.new_metadata or {})
                metadata["new_path_recovered_from"] = original_path
                metadata["new_path_recovered_at"] = time.time()
                row.new_metadata = metadata
                db.commit()
                logger.info(
                    "问题作品 new_path 已自动修正: conflict=%s old=%s -> new=%s",
                    conflict_id, original_path, resolved_path,
                )
            except Exception:
                db.rollback()
                logger.warning("修正 conflict.new_path 失败 conflict=%s", conflict_id, exc_info=True)
            finally:
                db.close()
        except Exception:
            logger.warning("修正 conflict.new_path 外层异常 conflict=%s", conflict_id, exc_info=True)

    def _read_stats_cache(self, conflict, side_key: str, current_path: str) -> Optional[dict[str, Any]]:
        if not current_path:
            return None
        metadata = dict(getattr(conflict, "new_metadata", None) or {})
        cache = metadata.get(f"{side_key}_stats_cache")
        if not isinstance(cache, dict):
            return None
        if str(cache.get("path") or "") != str(current_path):
            return None
        try:
            if not os.path.exists(current_path):
                return None
            current_mtime = os.path.getmtime(current_path)
        except OSError:
            return None
        cached_mtime = cache.get("mtime")
        if cached_mtime is None:
            return None
        try:
            if abs(float(cached_mtime) - current_mtime) > 1.0:
                return None
        except (TypeError, ValueError):
            return None
        stats = cache.get("stats")
        if not isinstance(stats, dict):
            return None
        return dict(stats)

    def _write_stats_cache(
        self, conflict_id: str, side_key: str, path: str, stats: dict[str, Any],
    ) -> None:
        if not conflict_id or not path or not isinstance(stats, dict):
            return
        # 失败/不存在/截断的 stats 不进缓存：下次刷新让其重新尝试算。
        if not stats.get("exists"):
            return
        if stats.get("truncated"):
            return
        try:
            from ..models.database import ConflictWork, get_db
            try:
                mtime = os.path.getmtime(path) if os.path.exists(path) else None
            except OSError:
                mtime = None
            db = next(get_db())
            try:
                row = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
                if not row:
                    return
                metadata = dict(row.new_metadata or {})
                metadata[f"{side_key}_stats_cache"] = {
                    "path": path,
                    "mtime": mtime,
                    "computed_at": time.time(),
                    "stats": dict(stats),
                }
                row.new_metadata = metadata
                db.commit()
            except Exception:
                db.rollback()
                logger.warning(
                    "写入 conflict %s 的 %s stats 缓存失败", conflict_id, side_key, exc_info=True,
                )
            finally:
                db.close()
        except Exception:
            logger.warning("写入 conflict stats 缓存外层失败", exc_info=True)

    def describe_conflict(self, conflict, include_stats: bool = False) -> dict[str, Any]:
        metadata = dict(conflict.new_metadata or {})
        existing_context = self.infer_library_context(
            conflict.existing_path,
            preferred_library_id=metadata.get("existing_library_id"),
        )
        source_context = self.infer_library_context(
            conflict.new_path,
            preferred_library_id=metadata.get("source_library_id") or metadata.get("target_library_id"),
        )
        return {
            "existing": {
                **existing_context,
                "stats": self._describe_local_path_stats(existing_context.get("path"))
                if include_stats and not existing_context.get("is_remote")
                else None,
            },
            "source": {
                **source_context,
                "stats": self._describe_local_path_stats(source_context.get("path"))
                if include_stats and not source_context.get("is_remote")
                else None,
            },
            "new_path_kind": "archive" if os.path.isfile(str(conflict.new_path or "")) else "folder",
            "metadata": metadata,
        }

    async def describe_conflict_async(self, conflict, include_stats: bool = False) -> dict[str, Any]:
        # 和 sync describe_conflict 的核心区别：
        # 1) 所有可能阻塞的本地 IO（os.walk / os.path.isfile）走 asyncio.to_thread，
        #    避免 /api/conflicts 列表加载时多个 conflict 串行卡死事件循环。
        # 2) source 路径用 _resolve_conflict_new_path 兜底找回（修复历史 bug 留下的死路径）。
        # 3) stats 走 (path, mtime) 持久化缓存：每个 conflict 只算一次，下次刷新直接拿。
        metadata = dict(conflict.new_metadata or {})

        # 兜底找回 source 路径：DB 里 conflict.new_path 可能是 /temp/RJxxx_subtask/... 死路径，
        # 真身已经在 {library_path}/_conflicts/{basename} 下。
        original_new_path = str(getattr(conflict, "new_path", "") or "").strip()
        resolved_new_path = self._resolve_conflict_new_path(conflict)
        if resolved_new_path and resolved_new_path != original_new_path:
            # 异步写回 DB（用独立 session）。这一步是 IO，但单条 SQL 很快，直接同步做完。
            self._maybe_persist_resolved_new_path(
                getattr(conflict, "id", ""), original_new_path, resolved_new_path,
            )

        existing_context = self.infer_library_context(
            conflict.existing_path,
            preferred_library_id=metadata.get("existing_library_id"),
        )
        source_context = self.infer_library_context(
            resolved_new_path,
            preferred_library_id=metadata.get("source_library_id") or metadata.get("target_library_id"),
        )

        existing: dict[str, Any] = {**existing_context, "stats": None}
        source: dict[str, Any] = {**source_context, "stats": None}

        # 如果 existing_path 是 Kikoeru 预检写入的显示标签（兼容旧 "[远程服务器]" 与新 "[Kikoeru 服务器]"），
        # 尝试通过 RJ 号在所有库存中搜索实际路径并重新计算统计信息。
        existing_path = str(existing.get("path") or "").strip()
        existing_resolved_remote = False
        if (
            (existing_path.startswith("[Kikoeru 服务器]") or existing_path.startswith("[远程服务器]"))
            and not existing.get("library_id")
        ):
            rjcode = str(getattr(conflict, "rjcode", "") or "").strip()
            if rjcode:
                resolved = await self._resolve_kikoeru_server_path(rjcode)
                if resolved:
                    existing.update(resolved)
                    existing_resolved_remote = bool(resolved.get("is_remote"))

        # 为 existing 与 source 并行计算 stats：
        # - 远程：await 现成 async _describe_remote_path_stats
        # - 本地：先查 (path, mtime) 持久化缓存，命中直接返回；未命中走 asyncio.to_thread + os.walk
        new_path_kind_task = asyncio.to_thread(
            lambda: "archive" if os.path.isfile(str(resolved_new_path or "")) else "folder",
        )

        conflict_id = str(getattr(conflict, "id", "") or "")

        async def _resolve_stats(side: dict[str, Any], side_key: str) -> Optional[dict[str, Any]]:
            if not include_stats:
                return None
            if side.get("is_remote"):
                return await self._describe_remote_path_stats(
                    side.get("library_id"),
                    side.get("path"),
                )
            local_path = str(side.get("path") or "").strip()
            cached = self._read_stats_cache(conflict, side_key, local_path)
            if cached is not None:
                return cached
            stats = await asyncio.to_thread(self._describe_local_path_stats, local_path)
            # 写缓存：os.walk 已经付费过了，写一次 DB 不阻塞调用方太多。
            await asyncio.to_thread(
                self._write_stats_cache, conflict_id, side_key, local_path, stats,
            )
            return stats

        existing_stats, source_stats, new_path_kind = await asyncio.gather(
            _resolve_stats(existing, "existing") if existing_resolved_remote or include_stats else _noop_stats(),
            _resolve_stats(source, "source") if include_stats else _noop_stats(),
            new_path_kind_task,
        )
        existing["stats"] = existing_stats
        source["stats"] = source_stats

        return {
            "existing": existing,
            "source": source,
            "new_path_kind": new_path_kind,
            "metadata": metadata,
        }

    async def _resolve_kikoeru_server_path(self, rjcode: str) -> Optional[dict[str, Any]]:
        """用 RJ 号解析 Kikoeru 写入的显示标签路径为库内真实路径。

        优先走 LibraryManager.find_rj_in_libraries（已接入 LibraryIndexService、起走索引快速路径、
        未 ready 的库走 SYNO.Search / os.walk fallback）。加总超时 20s 兑底远程 NAS
        崩块 / 占线场景，避免一条 conflict 拖垃整个列表响应。
        """
        try:
            manager = get_library_manager()
            matches = await asyncio.wait_for(
                manager.find_rj_in_libraries(rjcode),
                timeout=20.0,
            )
            if not matches:
                return None
            first = matches[0]
            lib_type = first.get("library_type") or "local"
            return {
                "library_id": first.get("library_id"),
                "library_type": lib_type,
                "library_name": first.get("library_name") or "",
                "path": first.get("path") or "",
                "is_remote": lib_type == "synology_filestation",
            }
        except asyncio.TimeoutError:
            logger.warning(
                "解析 Kikoeru 服务器路径超时 20s，跳过该条 conflict 的路径拾回： rjcode=%s",
                rjcode,
            )
        except Exception:
            logger.warning("无法通过 RJ 号解析 Kikoeru 服务器路径: rjcode=%s", rjcode, exc_info=True)
        return None

    def get_available_actions(self, conflict) -> list[str]:
        metadata = dict(conflict.new_metadata or {})
        if str(conflict.status or "").strip().upper() == "PROCESSING":
            if str(metadata.get("resolution_task_id") or "").strip():
                return ["CANCEL"]
        conflict_type_upper = str(conflict.conflict_type or "").upper()
        if conflict_type_upper in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            source_path = str(conflict.new_path or "").strip()
            if source_path and os.path.exists(source_path):
                return ["RETRY", "SKIP"]
            return ["SKIP"]
        if conflict_type_upper == "分卷压缩包后缀无法识别":
            disguised = metadata.get("disguised_volume_set")
            if isinstance(disguised, dict) and disguised.get("suspect_files"):
                return ["RENAME_VOLUMES", "SKIP"]
            # disguised payload 已被清掉的退化 case：通常是用户在前端
            # auto_retry=False 提交了重命名，conflict 仍然在 PENDING 状态。
            # 如果首卷路径还在，就允许走标准 RETRY；否则只能 SKIP。
            source_path = str(conflict.new_path or "").strip()
            if source_path and os.path.exists(source_path):
                return ["RETRY", "SKIP"]
            return ["SKIP"]

        # v1.6.122 之前创建的“原作目录已有字幕”问题项把可用操作固化成
        # ["SKIP"]。这些记录不会在新版本部署时自动重建；但只要目标目录仍
        # 是当前容器可见的真实目录，就允许复用既有 KEEP_NEW 的原子替换链路。
        # 不能泛化所有 LINKED_WORK，也不能对已不存在的旧目标开放删除操作。
        analysis_info = dict(getattr(conflict, "analysis_info", None) or {})
        is_legacy_existing_subtitle_conflict = (
            conflict_type_upper == "LINKED_WORK"
            and (
                str(metadata.get("reason") or "") == "原作目录已有字幕，按重复作品处理"
                or str(analysis_info.get("source_mode") or "")
                == "linked_translation_archive_existing_subtitle_conflict"
                or str(analysis_info.get("problem_kind") or "") == "existing_subtitles"
            )
        )
        existing_path = str(getattr(conflict, "existing_path", "") or "").strip()
        if is_legacy_existing_subtitle_conflict and existing_path and os.path.isdir(existing_path):
            return ["KEEP_NEW", "SKIP"]

        configured_actions = metadata.get("available_actions")
        if isinstance(configured_actions, list):
            actions: list[str] = []
            for action in configured_actions:
                try:
                    normalized = self.normalize_action(action)
                except ValueError:
                    continue
                if normalized not in actions:
                    actions.append(normalized)
            if actions:
                return actions

        description = self.describe_conflict(conflict)
        if description["existing"].get("path"):
            return ["KEEP_NEW", "SKIP", "MERGE"]
        return ["SKIP"]

    async def get_delete_preview(self, conflict) -> dict[str, Any]:
        description = await self.describe_conflict_async(conflict)
        existing = description["existing"]
        manager = get_library_manager()
        if existing["library_id"]:
            preview = await manager.delete(existing["library_id"], existing["path"], confirmed=False)
        else:
            preview = self._local_preview(existing["path"])
        preview["library_id"] = existing["library_id"]
        preview["library_type"] = existing["library_type"]
        preview["library_name"] = existing["library_name"]
        return preview

    async def create_merge_preview(self, conflict) -> dict[str, Any]:
        description = await self.describe_conflict_async(conflict)
        existing = description["existing"]
        if not existing["path"]:
            raise RuntimeError("Missing existing target path")
        if not conflict.new_path:
            raise RuntimeError("Missing new source path")

        await self.cleanup_conflict_sessions(conflict.id)
        workspace = self._create_workspace(conflict.id)
        session_registered = False

        try:
            source_path = self._resolve_conflict_new_path(conflict)
            original = str(getattr(conflict, "new_path", "") or "")
            if source_path and source_path != original:
                self._maybe_persist_resolved_new_path(
                    getattr(conflict, "id", ""), original, source_path,
                )
            if not source_path or not os.path.exists(source_path):
                raise self._new_source_missing_error(conflict)

            if os.path.isfile(source_path):
                staged_root = await self._stage_new_source(conflict, workspace)
                source_is_staged = True
            else:
                staged_root = source_path
                source_is_staged = False

            compare_service = get_folder_compare_service()

            remote_items = await self._load_existing_remote_items(existing)
            if remote_items is not None:
                compare_items = compare_service.build_compare_items_from_listing(
                    staged_root,
                    remote_items,
                    existing["path"],
                )
            else:
                if not os.path.exists(existing["path"]):
                    raise FileNotFoundError("Existing target directory does not exist")
                compare_items = compare_service.build_compare_items(staged_root, existing["path"])

            session_id = uuid.uuid4().hex
            session = ConflictMergeSession(
                id=session_id,
                conflict_id=str(conflict.id),
                workspace=workspace,
                staged_root=staged_root,
                existing_path=existing["path"],
                existing_library_id=existing["library_id"],
                existing_library_type=existing["library_type"],
                compare_items=compare_items,
                created_at=time.time(),
                source_is_staged=source_is_staged,
            )
            self._merge_sessions[session_id] = session
            session_registered = True
            decisions = compare_service.build_default_decisions(compare_items)

            return {
                "session_id": session_id,
                "conflict_id": str(conflict.id),
                "staged_root": staged_root,
                "existing_path": existing["path"],
                "existing_library_id": existing["library_id"],
                "existing_library_type": existing["library_type"],
                "items": compare_items,
                "default_decisions": decisions,
                "summary": compare_service.build_summary(compare_items),
            }
        except Exception:
            if not session_registered and os.path.isdir(workspace):
                await asyncio.to_thread(shutil.rmtree, workspace, True)
            raise

    # ============================================================
    # 合并预览 异步 job 模式
    # ============================================================
    # 同步版 create_merge_preview 在大压缩包 / 嵌套包 / 远程库存等场景下
    # 远超 nginx / 反向代理默认 60s 超时，用户固定看到 504。
    # 这里把整个流程包成异步 job：start_merge_preview 立即返回 job_id，worker 后台跑，
    # 前端轮询 GET /api/conflicts/{id}/preview-job/{job_id} 拿真实阶段 + 进度 + message。
    # 与日志记录一致：stage/stage_label/message 的语义对齐 ExtractService.update_progress。

    async def start_merge_preview(self, conflict) -> dict[str, Any]:
        """启动合并预览异步任务，立即返回 job_id 不阻塞 HTTP。"""
        # 入参基本校验：existing 路径与 conflict.new_path 必须存在
        description = await self.describe_conflict_async(conflict)
        existing = description["existing"]
        if not existing["path"]:
            raise RuntimeError("Missing existing target path")
        if not getattr(conflict, "new_path", None):
            raise RuntimeError("Missing new source path")

        # 如果该 conflict 已经有 running 的 job，直接复用，避免点两次合并就跑两遍 7z。
        # 同步阶段无法等 worker 完成，但前端拿 job_id 后会在 polling 里自然合并。
        for existing_job in self._merge_preview_jobs.values():
            if (
                existing_job.conflict_id == str(conflict.id)
                and existing_job.status == "running"
            ):
                return self._serialize_merge_preview_job(existing_job)

        # 兜底回收：清理掉 30 分钟以前的旧 job + 已完成 worker 句柄
        self.cleanup_old_merge_preview_jobs()

        job_id = uuid.uuid4().hex
        now = time.time()
        job = MergePreviewJob(
            id=job_id,
            conflict_id=str(conflict.id),
            status="running",
            stage="init",
            stage_label="初始化",
            message="启动合并预览任务",
            percent=2,
            created_at=now,
            updated_at=now,
        )
        self._merge_preview_jobs[job_id] = job
        worker = asyncio.create_task(
            self._run_merge_preview_worker(job_id, str(conflict.id))
        )
        self._merge_preview_workers[job_id] = worker
        return self._serialize_merge_preview_job(job)

    def get_merge_preview_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """同步快查 job 状态（前端轮询 endpoint 用）。"""
        job = self._merge_preview_jobs.get(str(job_id or "").strip())
        if not job:
            return None
        return self._serialize_merge_preview_job(job)

    def cleanup_old_merge_preview_jobs(self, max_age_seconds: int = 1800) -> None:
        """回收 30 分钟以上没活动的 job + 已完成 worker，避免内存泄漏。

        前端关弹窗就停止轮询，残留的 completed/failed job 在这里过期清掉；
        running 状态的也会按 updated_at 兜底清理（worker 卡死也一并 cancel）。
        """
        now = time.time()
        stale_ids = [
            jid for jid, job in self._merge_preview_jobs.items()
            if now - max(job.updated_at, job.created_at) > max_age_seconds
        ]
        for jid in stale_ids:
            self._merge_preview_jobs.pop(jid, None)
            worker = self._merge_preview_workers.pop(jid, None)
            if worker and not worker.done():
                worker.cancel()

    async def _run_merge_preview_worker(self, job_id: str, conflict_id: str) -> None:
        """后台 worker：复刻 create_merge_preview 流程，每个阶段切换都更新 job。"""
        job = self._merge_preview_jobs.get(job_id)
        if not job:
            return
        # 跨 asyncio.task 不持有外层传进来的 SQLAlchemy 实例，重新 fetch 一份。
        # 读完立即 expunge + close：后续 _stage_new_source_with_progress / extract /
        # _load_existing_remote_items 等长 IO 不再占用连接池槽位。WAL 模式下读虽然
        # 不阻塞写，但 connection pool 总共只有 15 槽（pool_size=5+max_overflow=10），
        # 多个并发预览同时跑会迅速耗尽，让其他 endpoint 拿不到连接。
        from ..models.database import ConflictWork, get_db
        db = next(get_db())
        workspace = ""
        session_registered = False
        try:
            try:
                conflict = (
                    db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
                )
                if not conflict:
                    self._fail_merge_preview_job(job, f"找不到 conflict 记录：{conflict_id}")
                    return
                # detach：后续访问 conflict.x 都不再走 session
                db.expunge(conflict)
            finally:
                try:
                    db.close()
                except Exception:
                    logger.debug("合并预览 worker 关闭只读 db session 失败", exc_info=True)
                db = None  # 顶层 finally 不再 double close

            self._update_merge_preview_job(
                job, stage="init", stage_label="初始化",
                percent=5, message="读取冲突描述",
            )
            description = await self.describe_conflict_async(conflict)
            existing = description["existing"]
            if not existing["path"]:
                raise RuntimeError("Missing existing target path")

            await self.cleanup_conflict_sessions(conflict.id)
            workspace = self._create_workspace(conflict.id)

            self._update_merge_preview_job(
                job, stage="resolve_path", stage_label="定位新版本来源",
                percent=10, message="尝试 _conflicts 多级 fallback",
            )
            source_path = self._resolve_conflict_new_path(conflict)
            original = str(getattr(conflict, "new_path", "") or "")
            if source_path and source_path != original:
                self._maybe_persist_resolved_new_path(
                    getattr(conflict, "id", ""), original, source_path,
                )
            if not source_path or not os.path.exists(source_path):
                raise self._new_source_missing_error(conflict)

            if os.path.isfile(source_path):
                # 压缩包：copy_archive → extract（含嵌套 + monitor）→ filter
                staged_root = await self._stage_new_source_with_progress(
                    conflict, workspace, job, source_path,
                )
                source_is_staged = True
            else:
                # 目录：跳过 copytree，直接对比；进度直接跳到扫描阶段
                self._update_merge_preview_job(
                    job, stage="scan_source", stage_label="读取新版目录",
                    percent=58, message="目录来源跳过复制，直接进入对比",
                )
                staged_root = source_path
                source_is_staged = False

            scan_label = "读取远程库存清单" if existing.get("is_remote") else "扫描库存目录"
            self._update_merge_preview_job(
                job, stage="scan_existing", stage_label=scan_label,
                percent=72, message=existing.get("path") or "",
            )
            compare_service = get_folder_compare_service()
            remote_items = await self._load_existing_remote_items(existing)
            if remote_items is not None:
                compare_items = compare_service.build_compare_items_from_listing(
                    staged_root, remote_items, existing["path"],
                )
            else:
                if not os.path.exists(existing["path"]):
                    raise FileNotFoundError("Existing target directory does not exist")
                compare_items = compare_service.build_compare_items(staged_root, existing["path"])

            self._update_merge_preview_job(
                job, stage="compare", stage_label="生成差异树",
                percent=92,
                message=f"按相对路径配对 {len(compare_items)} 项",
            )
            session_id = uuid.uuid4().hex
            session = ConflictMergeSession(
                id=session_id,
                conflict_id=str(conflict.id),
                workspace=workspace,
                staged_root=staged_root,
                existing_path=existing["path"],
                existing_library_id=existing["library_id"],
                existing_library_type=existing["library_type"],
                compare_items=compare_items,
                created_at=time.time(),
                source_is_staged=source_is_staged,
            )
            self._merge_sessions[session_id] = session
            session_registered = True
            decisions = compare_service.build_default_decisions(compare_items)

            preview = {
                "session_id": session_id,
                "conflict_id": str(conflict.id),
                "staged_root": staged_root,
                "existing_path": existing["path"],
                "existing_library_id": existing["library_id"],
                "existing_library_type": existing["library_type"],
                "items": compare_items,
                "default_decisions": decisions,
                "summary": compare_service.build_summary(compare_items),
            }
            self._update_merge_preview_job(
                job, stage="done", stage_label="完成", percent=100,
                message=f"已生成 {len(compare_items)} 项差异",
                status="completed", result=preview,
            )
        except FileNotFoundError as exc:
            self._fail_merge_preview_job(job, str(exc))
        except asyncio.CancelledError:
            # worker 被外部 cancel（cleanup_old_merge_preview_jobs 命中），静默退出
            self._fail_merge_preview_job(job, "任务已取消")
            raise
        except Exception as exc:
            logger.error("合并预览 worker 失败 job=%s conflict=%s: %s", job_id, conflict_id, exc, exc_info=True)
            self._fail_merge_preview_job(job, str(exc) or "合并预览失败")
        finally:
            if workspace and not session_registered and os.path.isdir(workspace):
                await asyncio.to_thread(shutil.rmtree, workspace, True)
            # db 在前面 try/finally 内已经 close（成功路径）；这里只处理"还没到那一步
            # 就抛异常"的极端场景，避免连接泄漏。
            if db is not None:
                try:
                    db.close()
                except Exception:
                    logger.debug("合并预览 worker 关闭 db session 失败", exc_info=True)
            self._merge_preview_workers.pop(job_id, None)

    async def _stage_new_source_with_progress(
        self, conflict, workspace: str, job: "MergePreviewJob", source_path: str,
    ) -> str:
        """带进度上报的 staging：复制压缩包 → 解压（含 monitor）→ filter。"""
        self._update_merge_preview_job(
            job, stage="copy_archive", stage_label="复制压缩包",
            percent=15,
            message=f"把 {os.path.basename(source_path)} 放入合并工作区",
        )
        staged_archive_path = os.path.join(workspace, os.path.basename(source_path))
        await self._copy_to_stage_with_budget(
            source_path,
            staged_archive_path,
            is_dir=False,
            reason="conflict.preview_stage_archive",
        )

        self._update_merge_preview_job(
            job, stage="extract", stage_label="解压新包",
            percent=22, message="启动 7z 解压子进程",
        )
        extract_task = Task(
            task_type=TaskType.EXTRACT,
            source_path=staged_archive_path,
            auto_classify=False,
            skip_archive=True,
        )

        # 并行 monitor：每 0.4s 把 extract_task.progress / current_step 同步到 job，
        # 让前端能看到 "解压中 50%"、"检查嵌套压缩包"、"嵌套解压 RJxxx (层1)" 等真实阶段。
        monitor = asyncio.create_task(
            self._monitor_extract_into_job(extract_task, job)
        )
        try:
            extracted_path = await ExtractService().extract(extract_task)
        finally:
            monitor.cancel()
            try:
                await monitor
            except (asyncio.CancelledError, Exception):
                pass

        if not extracted_path:
            raise RuntimeError(extract_task.error_message or "Extract failed")
        staged_root = extracted_path

        self._update_merge_preview_job(
            job, stage="filter", stage_label="过滤临时目录",
            percent=64, message="按项目规则清理无效文件",
        )
        filter_task = Task(
            task_type=TaskType.FILTER,
            source_path=staged_root,
            auto_classify=False,
            skip_archive=True,
        )
        await FilterService().filter(staged_root, filter_task)
        return staged_root

    async def _monitor_extract_into_job(
        self, extract_task: "Task", job: "MergePreviewJob",
    ) -> None:
        """周期把 extract_task 的 progress / current_step 同步到 job。

        ExtractService 内部 `task.update_progress` 会刷 task.progress + task.current_step：
          - 5% 等待文件写入完成 / 10% 检测文件类型 / 15% 等待分卷组完整
          - 20% 读取压缩包内容 / 30% 开始解压 / 30~88% 解压中 X%
          - 90% 验证解压完整性 / 95% 检查嵌套压缩包 / 97% 检查文件名编码
        把 0~100 映射到 job 的 22~62 区间，避免和外层阶段切换冲突 + 进度回退。
        """
        last_step = ""
        try:
            while True:
                await asyncio.sleep(0.4)
                inner = int(getattr(extract_task, "progress", 0) or 0)
                step = str(getattr(extract_task, "current_step", "") or "解压中").strip()
                mapped = 22 + int(min(100, max(0, inner)) * 0.4)

                stage = "extract"
                stage_label = "解压新包"
                # current_step 关键字识别真实子阶段，让前端 chip 跟着切
                lower_step = step.lower()
                if "嵌套" in step or "nested" in lower_step:
                    stage = "nested_extract"
                    stage_label = "嵌套解压"
                elif "验证" in step or "verify" in lower_step:
                    stage_label = "验证解压完整性"
                elif "文件名编码" in step:
                    stage_label = "检查文件名编码"
                elif "等待" in step:
                    stage_label = "等待写入完成"
                elif "检测" in step:
                    stage_label = "检测文件类型"
                elif "分卷" in step:
                    stage_label = "等待分卷组完整"
                elif "读取" in step:
                    stage_label = "读取压缩包内容"

                # 仅在 step 文案变化或进度推进时更新，减少无意义写
                if step != last_step or mapped > job.percent:
                    self._update_merge_preview_job(
                        job, stage=stage, stage_label=stage_label,
                        percent=mapped, message=step,
                    )
                    last_step = step
        except asyncio.CancelledError:
            return
        except Exception:
            logger.debug("merge preview extract monitor 异常", exc_info=True)

    def _update_merge_preview_job(
        self, job: Optional["MergePreviewJob"], **kwargs: Any,
    ) -> None:
        """统一更新 job 字段；percent 永远不回退；自动刷新 updated_at。"""
        if not job:
            return
        for key in ("stage", "stage_label", "message", "status", "error"):
            value = kwargs.get(key)
            if value is not None:
                setattr(job, key, value)
        if "result" in kwargs and kwargs["result"] is not None:
            job.result = kwargs["result"]
        new_percent = kwargs.get("percent")
        if new_percent is not None:
            try:
                pct = int(new_percent)
                if pct > job.percent:
                    job.percent = min(100, pct)
            except (TypeError, ValueError):
                pass
        job.updated_at = time.time()
        self._broadcast_merge_preview_job(job)

    def _fail_merge_preview_job(self, job: Optional["MergePreviewJob"], error: str) -> None:
        if not job:
            return
        msg = str(error or "未知错误")
        job.status = "failed"
        job.stage = "failed"
        job.stage_label = "失败"
        job.message = msg
        job.error = msg
        job.updated_at = time.time()
        self._broadcast_merge_preview_job(job)

    def _broadcast_merge_preview_job(self, job: "MergePreviewJob") -> None:
        try:
            from .realtime_event_service import broadcast_event

            updated_at = datetime.fromtimestamp(job.updated_at or time.time()).isoformat()
            broadcast_event({
                "type": "job.conflict_merge_preview.changed",
                "reason": job.stage or "progress",
                "id": job.id,
                "domain": "conflict_resolution",
                "status": job.status,
                "progress": int(job.percent or 0),
                "current_step": job.message or job.stage_label or "",
                "updated_at": updated_at,
                "payload": {
                    "job_id": job.id,
                    "conflict_id": job.conflict_id,
                    "status": job.status,
                    "stage": job.stage,
                    "stage_label": job.stage_label,
                    "message": job.message,
                    "percent": int(job.percent or 0),
                    "error": job.error,
                    "updated_at": job.updated_at,
                },
            })
        except Exception:
            logger.debug("广播合并预览实时事件失败", exc_info=True)

    def _serialize_merge_preview_job(self, job: "MergePreviewJob") -> dict[str, Any]:
        return {
            "job_id": job.id,
            "conflict_id": job.conflict_id,
            "status": job.status,
            "stage": job.stage,
            "stage_label": job.stage_label,
            "message": job.message,
            "percent": job.percent,
            "result": job.result,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    async def resolve_keep_new(self, conflict) -> dict[str, Any]:
        description = await self.describe_conflict_async(conflict)
        existing = description["existing"]
        workspace = self._create_workspace(conflict.id)
        try:
            staged_root = await self._stage_new_source(conflict, workspace)

            if existing["library_id"] and existing["is_remote"]:
                manager = get_library_manager()
                final_path = await manager.replace_remote_directory_with_local(
                    existing["library_id"],
                    staged_root,
                    existing["path"],
                )
            else:
                final_path = await asyncio.to_thread(
                    get_folder_compare_service().safe_replace_directory,
                    staged_root,
                    existing["path"],
                )

            # 索引同步：替换完成后先 delete 旧子树（防孤儿），再 upsert 新子树
            self._notify_index_after_conflict_resolution(
                existing.get("library_id"),
                existing.get("path"),
                final_path,
            )

            await self._finalize_new_source(conflict)
            await self.cleanup_conflict_sessions(conflict.id)
            return {
                "message": "已采用新版本内容替换现有目录",
                "final_path": final_path,
            }
        finally:
            if os.path.isdir(workspace):
                await asyncio.to_thread(shutil.rmtree, workspace, True)

    async def resolve_skip(self, conflict) -> dict[str, Any]:
        description = self.describe_conflict(conflict)
        source = description["source"]
        # 走 fallback 路径，避免老 conflict 数据 new_path 死路径导致 _conflicts/ 残留。
        delete_target = self._resolve_conflict_new_path(conflict) or conflict.new_path
        await self._delete_source_path(delete_target, source.get("library_id"))
        await self.cleanup_conflict_sessions(conflict.id)
        return {
            "message": "已跳过当前压缩包或目录，并删除待处理来源",
            "deleted_path": delete_target,
        }

    async def rename_disguised_volumes(
        self,
        conflict,
        renames: List[dict[str, str]],
    ) -> dict[str, Any]:
        """对伪装多卷 conflict 执行用户确认后的逐卷重命名。

        ``renames`` 是 ``[{"old": str, "new": str}, ...]``。校验项（任意一项失败立即抛 ValueError）：

        - conflict.conflict_type 必须是 ``分卷压缩包后缀无法识别``。
        - new_metadata.disguised_volume_set.suspect_files 必须存在。
        - 每个 ``old`` 都要在 suspect 路径集合里，避免被构造请求改到任意目录。
        - ``new`` 必须落在同一目录、不能跳出（防 ``..``）、basename 不能为空、
          basename 不能含路径分隔符。
        - ``new`` 目标不能已经存在（除非就是某个 suspect 文件本身）。
        - rename 全集要覆盖所有 suspect_files，且不能漏掉任何首卷。

        校验通过后做"两阶段原子重命名"：先全部改到一个临时名 (.kikoeru-rename-<id>.tmp)，
        再改到目标名。任意一步失败立刻把已改的回滚。最后更新 ``conflict.new_path``
        指向新的首卷，metadata 清掉 disguised payload，记录 rename 历史。
        """
        conflict_type_upper = str(conflict.conflict_type or "").upper()
        if conflict_type_upper != "分卷压缩包后缀无法识别":
            raise ValueError("当前问题类型不支持手动重命名分卷")

        metadata = dict(conflict.new_metadata or {})
        disguised = metadata.get("disguised_volume_set")
        if not isinstance(disguised, dict) or not disguised.get("suspect_files"):
            raise ValueError("缺少分卷探测信息，无法执行重命名")

        suspect_files = list(disguised.get("suspect_files") or [])
        suspect_paths = {
            os.path.normcase(os.path.normpath(str(item.get("path") or "")))
            for item in suspect_files
            if item.get("path")
        }
        if not suspect_paths:
            raise ValueError("分卷探测信息为空")

        directory = str(disguised.get("directory") or "").strip()
        if not directory or not os.path.isdir(directory):
            raise ValueError("分卷所在目录不存在")
        directory_norm = os.path.normcase(os.path.normpath(directory))

        if not renames or len(renames) != len(suspect_files):
            raise ValueError("重命名条数必须等于探测到的分卷数")

        # 校验每条 rename
        normalized_pairs: List[Tuple[str, str]] = []
        seen_olds: set[str] = set()
        seen_news: set[str] = set()
        for entry in renames:
            old_raw = str(entry.get("old") or "").strip()
            new_raw = str(entry.get("new") or "").strip()
            if not old_raw or not new_raw:
                raise ValueError("分卷映射的旧路径和新路径都不能为空")

            old_abs = os.path.normpath(old_raw)
            old_key = os.path.normcase(old_abs)
            if old_key in seen_olds:
                raise ValueError(f"重复的源分卷路径: {old_raw}")
            seen_olds.add(old_key)
            if old_key not in suspect_paths:
                raise ValueError(f"源分卷不在探测列表内: {old_raw}")

            # 任何 ".." 路径段直接拒（防跳出目录）
            parts = new_raw.replace("\\", "/").split("/")
            if any(p == ".." for p in parts):
                raise ValueError(f"新路径不能包含 ..: {new_raw}")

            if os.path.isabs(new_raw):
                # 绝对路径写法：basename + dir 必须落在 directory 内
                new_abs = os.path.normpath(new_raw)
                new_basename = os.path.basename(new_abs)
            else:
                # 相对路径写法：只允许单一文件名，不允许含分隔符
                if "/" in new_raw or "\\" in new_raw:
                    raise ValueError(f"新文件名不能包含路径分隔符: {new_raw}")
                new_basename = new_raw
                new_abs = os.path.normpath(os.path.join(directory, new_basename))

            if not new_basename or new_basename in {".", ".."}:
                raise ValueError(f"新文件名无效: {new_raw}")

            new_key = os.path.normcase(new_abs)
            new_dir_norm = os.path.normcase(os.path.normpath(os.path.dirname(new_abs)))
            if new_dir_norm != directory_norm:
                raise ValueError(f"新路径必须在同一目录: {new_raw}")
            if new_key in seen_news:
                raise ValueError(f"新文件名重复: {new_basename}")
            seen_news.add(new_key)

            normalized_pairs.append((old_abs, new_abs))

        # new 不能与现有非 suspect 文件冲突（如果 new 就是某个 suspect，那是允许的：
        # 因为我们会在第一阶段先把 suspect 全部改到 .tmp）
        for _, new_abs in normalized_pairs:
            if not os.path.exists(new_abs):
                continue
            new_key = os.path.normcase(new_abs)
            if new_key not in suspect_paths:
                raise ValueError(f"目标文件已存在且非分卷: {new_abs}")

        # 两阶段原子重命名
        rename_id = uuid.uuid4().hex[:8]
        stage1: List[Tuple[str, str]] = []  # old -> tmp
        stage2: List[Tuple[str, str]] = []  # tmp -> new
        try:
            # Stage 1: old -> tmp
            for idx, (old_abs, new_abs) in enumerate(normalized_pairs):
                if not os.path.exists(old_abs):
                    raise ValueError(f"源分卷已不存在: {old_abs}")
                tmp_path = os.path.join(
                    directory,
                    f".kikoerumanager-rename-{rename_id}-{idx:03d}.tmp",
                )
                await asyncio.to_thread(os.rename, old_abs, tmp_path)
                stage1.append((old_abs, tmp_path))
                stage2.append((tmp_path, new_abs))

            # Stage 2: tmp -> new
            for tmp_path, new_abs in stage2:
                await asyncio.to_thread(os.rename, tmp_path, new_abs)
        except Exception as exc:
            # Stage 2 失败 → 把已经改成 new 的退回 tmp，然后所有 tmp 退回 old
            logger.error("[RenameVolumes] 重命名失败，开始回滚: %s", exc, exc_info=True)
            for tmp_path, new_abs in stage2:
                if os.path.exists(new_abs) and not os.path.exists(tmp_path):
                    try:
                        await asyncio.to_thread(os.rename, new_abs, tmp_path)
                    except Exception:
                        logger.error(
                            "[RenameVolumes] 回滚 stage2 失败: %s -> %s",
                            new_abs,
                            tmp_path,
                            exc_info=True,
                        )
            for old_abs, tmp_path in stage1:
                if os.path.exists(tmp_path) and not os.path.exists(old_abs):
                    try:
                        await asyncio.to_thread(os.rename, tmp_path, old_abs)
                    except Exception:
                        logger.error(
                            "[RenameVolumes] 回滚 stage1 失败: %s -> %s",
                            tmp_path,
                            old_abs,
                            exc_info=True,
                        )
            raise

        # 把 conflict.new_path 改成首卷的新路径，让后续 retry 任务能拿对路径。
        first_new = normalized_pairs[0][1]
        next_metadata = dict(metadata)
        next_metadata.pop("disguised_volume_set", None)
        next_metadata["volume_rename_history"] = [
            {"old": old, "new": new}
            for old, new in normalized_pairs
        ]
        next_metadata["volume_rename_at"] = datetime.now().isoformat()

        conflict.new_path = first_new
        conflict.new_metadata = next_metadata

        return {
            "renamed": [
                {"old": old, "new": new}
                for old, new in normalized_pairs
            ],
            "first_volume": first_new,
            "directory": directory,
        }

    async def resolve_merge(
        self,
        conflict,
        session_id: Optional[str],
        decisions: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        session = self._merge_sessions.get(str(session_id or "").strip())
        if not session or session.conflict_id != str(conflict.id):
            preview = await self.create_merge_preview(conflict)
            session = self._merge_sessions.get(preview["session_id"])
        if not session:
            raise RuntimeError("Merge preview session not found")

        # 懒惰暂存：预览时目录来源跳过了 copytree，真正合并前在此补做
        if not session.source_is_staged:
            source_path = session.staged_root  # 此时 staged_root 存放的是原始源目录
            staged_dir = os.path.join(session.workspace, os.path.basename(source_path))
            logger.info("合并执行：开始暂存源目录 %s -> %s", source_path, staged_dir)
            await self._copy_to_stage_with_budget(
                source_path,
                staged_dir,
                is_dir=True,
                reason="conflict.merge_stage_dir",
            )
            filter_task = Task(
                task_type=TaskType.FILTER,
                source_path=staged_dir,
                auto_classify=False,
                skip_archive=True,
            )
            await FilterService().filter(staged_dir, filter_task)
            session.staged_root = staged_dir
            session.source_is_staged = True

        compare_service = get_folder_compare_service()
        normalized_decisions = compare_service.normalize_decisions(session.compare_items, decisions or {})

        if session.existing_library_id and session.existing_library_type == "synology_filestation":
            manager = get_library_manager()
            final_path = await manager.merge_remote_directory_with_local(
                session.existing_library_id,
                session.existing_path,
                session.staged_root,
                session.compare_items,
                normalized_decisions,
            )
        else:
            final_path = await asyncio.to_thread(
                compare_service.apply_merge,
                session.staged_root,
                session.existing_path,
                normalized_decisions,
                session.existing_path,
            )

        # 索引同步：合并完成后先 delete 旧子树，再 upsert 新子树
        self._notify_index_after_conflict_resolution(
            session.existing_library_id,
            session.existing_path,
            final_path,
        )

        await self._finalize_new_source(conflict)
        await self.cleanup_conflict_sessions(conflict.id)
        return {
            "message": "合并结果已生成并写入目标目录",
            "final_path": final_path,
        }

    def _notify_index_after_conflict_resolution(
        self,
        library_id: Optional[str],
        existing_path: Optional[str],
        final_path: Optional[str],
    ) -> None:
        """KEEP_NEW / MERGE 落地后通知索引：先 delete 旧子树，再 upsert 新子树。

        失败静默；任意一步异常都不影响接口返回。
        """
        try:
            if not library_id or not final_path:
                return
            manager = get_library_manager()
            try:
                library = manager.get_library_definition(library_id)
            except Exception:
                logger.debug(
                    "[索引] 冲突解决：解析库存定义失败 library_id=%s",
                    library_id, exc_info=True,
                )
                return
            if existing_path and os.path.abspath(existing_path) == os.path.abspath(final_path):
                manager._enqueue_index_replace_subtree_many(library, [final_path])
                return
            if existing_path:
                manager._enqueue_index_delete_many(library, [existing_path])
            manager._enqueue_index_upsert_subtree_many(library, [final_path])
        except Exception:
            logger.debug(
                "[索引] 冲突解决后通知索引失败 library_id=%s final=%s",
                library_id, final_path, exc_info=True,
            )

    async def cleanup_conflict_sessions(self, conflict_id: str) -> None:
        target_conflict_id = str(conflict_id or "")
        stale_ids = [
            session_id
            for session_id, session in self._merge_sessions.items()
            if session.conflict_id == target_conflict_id
        ]
        for session_id in stale_ids:
            session = self._merge_sessions.pop(session_id, None)
            if session and os.path.exists(session.workspace):
                await asyncio.to_thread(shutil.rmtree, session.workspace, True)

    def _create_workspace(self, conflict_id: str) -> str:
        temp_root = get_config().storage.temp_path
        os.makedirs(temp_root, exist_ok=True)
        return tempfile.mkdtemp(prefix=f"conflict_{conflict_id}_", dir=temp_root)

    async def _copy_to_stage_with_budget(self, source_path: str, target_path: str, *, is_dir: bool, reason: str) -> None:
        async with get_resource_budget_service().acquire("disk_io_local", reason=reason):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            if is_dir:
                await asyncio.to_thread(shutil.copytree, source_path, target_path)
            else:
                await asyncio.to_thread(shutil.copy2, source_path, target_path)

    async def _stage_new_source(self, conflict, workspace: str) -> str:
        # 兜底找回 source：DB 里 conflict.new_path 可能是已经被搬走 / 清理的临时路径，
        # 真实数据其实在 {library_path}/_conflicts/{basename}。
        source_path = self._resolve_conflict_new_path(conflict)
        original = str(getattr(conflict, "new_path", "") or "")
        if source_path and source_path != original:
            self._maybe_persist_resolved_new_path(
                getattr(conflict, "id", ""), original, source_path,
            )
        if not source_path or not os.path.exists(source_path):
            raise self._new_source_missing_error(conflict)

        if os.path.isfile(source_path):
            staged_archive_path = os.path.join(workspace, os.path.basename(source_path))
            await self._copy_to_stage_with_budget(
                source_path,
                staged_archive_path,
                is_dir=False,
                reason="conflict.stage_archive",
            )
            extract_task = Task(
                task_type=TaskType.EXTRACT,
                source_path=staged_archive_path,
                auto_classify=False,
                skip_archive=True,
            )
            extracted_path = await ExtractService().extract(extract_task)
            if not extracted_path:
                raise RuntimeError(extract_task.error_message or "Extract failed")
            staged_root = extracted_path
        else:
            staged_root = os.path.join(workspace, os.path.basename(source_path))
            await self._copy_to_stage_with_budget(
                source_path,
                staged_root,
                is_dir=True,
                reason="conflict.stage_dir",
            )

        filter_task = Task(
            task_type=TaskType.FILTER,
            source_path=staged_root,
            auto_classify=False,
            skip_archive=True,
        )
        await FilterService().filter(staged_root, filter_task)
        return staged_root

    async def _finalize_new_source(self, conflict) -> None:
        description = self.describe_conflict(conflict)
        source = description["source"]
        # 走 fallback 路径，否则 conflict.new_path 还是 /temp/RJxxx_subtask 死路径时
        # 不会真正清掉 {library_path}/_conflicts/{basename} 的数据。
        delete_target = self._resolve_conflict_new_path(conflict) or conflict.new_path
        await self._delete_source_path(delete_target, source.get("library_id"))

    async def _delete_source_path(self, path: Optional[str], library_id: Optional[str]) -> None:
        target_path = str(path or "").strip()
        if not target_path:
            return
        manager = get_library_manager()
        if library_id:
            await manager.delete(library_id, target_path, confirmed=True)
            return
        if not os.path.exists(target_path):
            return
        if os.path.isdir(target_path):
            await asyncio.to_thread(shutil.rmtree, target_path, True)
        else:
            await asyncio.to_thread(self._delete_local_file_with_split_siblings, target_path)

    def _delete_local_file_with_split_siblings(self, path: str) -> None:
        """删除本地来源文件；如果它是分卷成员，同步删除整组和空父目录。"""
        targets = self._collect_local_split_archive_siblings(path)
        for target in targets:
            if not os.path.exists(target):
                continue
            try:
                os.remove(target)
                logger.info("[ConflictSkip] 已删除来源文件: %s", target)
            except FileNotFoundError:
                continue
        parent_dir = os.path.dirname(path)
        if not parent_dir or not os.path.isdir(parent_dir):
            return
        try:
            if not os.listdir(parent_dir):
                os.rmdir(parent_dir)
                logger.info("[ConflictSkip] 已删除空来源目录: %s", parent_dir)
        except OSError as exc:
            logger.debug("[ConflictSkip] 来源目录非空或不可删除，保留: %s error=%s", parent_dir, exc)

    def _collect_local_split_archive_siblings(self, path: str) -> list[str]:
        """收集同目录下与 path 属于同一分卷组的本地文件。"""
        if not os.path.isfile(path):
            return [path] if os.path.exists(path) else []

        parent_dir = os.path.dirname(path)
        filename = os.path.basename(path)
        patterns: list[re.Pattern[str]] = []

        def add_pattern(pattern: str) -> None:
            patterns.append(re.compile(pattern, re.IGNORECASE))

        # X.001 / X.002 / ...：用户这次残留的形态。
        match = re.match(r"^(.+)\.(\d{3})$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.\d{{3}}$")

        # X.zip.001 / X.7z.001 / X.tar.001 / X.rar.001 等。
        match = re.match(r"^(.+\.[a-zA-Z][a-zA-Z0-9]{0,3})\.\d{3}$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.\d{{3}}$")

        # X.zip + X.002 / X.003 ...（zip_numeric_split 回滚后形态）。
        match = re.match(r"^(.+)\.zip$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.zip$")
            add_pattern(rf"^{base}\.\d{{3}}$")

        # X.part1.rar / X.part2.rar；也兼容无扩展 X.part1 / X.part2。
        match = re.match(r"^(.+)\.part\d+\.(rar|zip|7z|exe)$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.part\d+\.(rar|zip|7z|exe)$")
        match = re.match(r"^(.+)\.part\d+$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.part\d+$")

        # ZIP / SFX / 旧 RAR 分卷。
        match = re.match(r"^(.+)\.z\d{2}$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.zip$")
            add_pattern(rf"^{base}\.z\d{{2}}$")
        match = re.match(r"^(.+)\.exe$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.exe$")
            add_pattern(rf"^{base}\.e\d{{2}}$")
        match = re.match(r"^(.+)\.e\d{2}$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.exe$")
            add_pattern(rf"^{base}\.e\d{{2}}$")
        match = re.match(r"^(.+)\.rar$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.rar$")
            add_pattern(rf"^{base}\.r\d{{2}}$")
        match = re.match(r"^(.+)\.r\d{2}$", filename, re.IGNORECASE)
        if match:
            base = re.escape(match.group(1))
            add_pattern(rf"^{base}\.rar$")
            add_pattern(rf"^{base}\.r\d{{2}}$")

        if not patterns:
            return [path]

        siblings: set[str] = {path}
        try:
            with os.scandir(parent_dir) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    if any(pattern.match(entry.name) for pattern in patterns):
                        siblings.add(entry.path)
        except OSError:
            return [path]

        return sorted(siblings, key=lambda item: os.path.basename(item).lower())

    def _local_preview(self, path: str) -> dict[str, Any]:
        if not path or not os.path.exists(path):
            raise FileNotFoundError("Target path does not exist")
        if os.path.isdir(path):
            size = 0
            file_count = 0
            folder_count = 1
            for root, dirs, files in os.walk(path):
                folder_count += len(dirs)
                file_count += len(files)
                for filename in files:
                    file_path = os.path.join(root, filename)
                    try:
                        size += os.path.getsize(file_path)
                    except OSError:
                        continue
            return {
                "need_confirm": True,
                "type": "folder",
                "name": os.path.basename(path),
                "path": path,
                "size": size,
                "file_count": file_count,
                "folder_count": folder_count,
            }
        return {
            "need_confirm": True,
            "type": "file",
            "name": os.path.basename(path),
            "path": path,
            "size": os.path.getsize(path),
            "file_count": 1,
            "folder_count": 0,
        }


_conflict_resolution_service: Optional[ConflictResolutionService] = None


def get_conflict_resolution_service() -> ConflictResolutionService:
    global _conflict_resolution_service
    if _conflict_resolution_service is None:
        _conflict_resolution_service = ConflictResolutionService()
    return _conflict_resolution_service
