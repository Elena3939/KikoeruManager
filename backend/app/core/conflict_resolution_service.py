import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

from ..config.settings import get_config
from ..core.extract_service import ExtractService
from ..core.filter_service import FilterService
from ..core.folder_compare_service import get_folder_compare_service
from ..core.library_manager import get_library_manager
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


class ConflictResolutionService:
    def __init__(self) -> None:
        self._merge_sessions: dict[str, ConflictMergeSession] = {}

    def normalize_action(self, action: str) -> str:
        normalized = str(action or "").strip().upper()
        if normalized == "KEEP_OLD":
            return "SKIP"
        if normalized in {"KEEP_BOTH", "MERGE_LANG"}:
            return "MERGE"
        if normalized not in {"KEEP_NEW", "MERGE", "SKIP"}:
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
        candidate = str(getattr(conflict, "new_path", "") or "").strip()
        if not candidate:
            return candidate
        if os.path.exists(candidate):
            return candidate
        basename = os.path.basename(candidate)
        if not basename:
            return candidate
        try:
            library_path = str(getattr(get_config().storage, "library_path", "") or "").strip()
        except Exception:
            return candidate
        if not library_path:
            return candidate
        fallback = os.path.join(library_path, "_conflicts", basename)
        if os.path.exists(fallback):
            return fallback
        return candidate

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
        if str(conflict.conflict_type or "").upper() in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            source_path = str(conflict.new_path or "").strip()
            if source_path and os.path.exists(source_path):
                return ["RETRY", "SKIP"]
            return ["SKIP"]

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

        # 判断来源是文件（需要解压才能对比）还是目录
        # 目录来源跳过耗时的 shutil.copytree，直接用原始路径构建对比列表；
        # 真正执行 merge 时才在 resolve_merge 里懒惰暂存。
        source_path = self._resolve_conflict_new_path(conflict)
        original = str(getattr(conflict, "new_path", "") or "")
        if source_path and source_path != original:
            self._maybe_persist_resolved_new_path(
                getattr(conflict, "id", ""), original, source_path,
            )
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("New source does not exist")

        if os.path.isfile(source_path):
            # 压缩包：解压不可避免，走完整 staging 流程
            staged_root = await self._stage_new_source(conflict, workspace)
            source_is_staged = True
        else:
            # 目录：直接引用原始路径，跳过耗时 copytree
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

    async def resolve_keep_new(self, conflict) -> dict[str, Any]:
        description = await self.describe_conflict_async(conflict)
        existing = description["existing"]
        staged_root = await self._stage_new_source(conflict, self._create_workspace(conflict.id))

        if existing["library_id"] and existing["is_remote"]:
            manager = get_library_manager()
            final_path = await manager.replace_remote_directory_with_local(
                existing["library_id"],
                staged_root,
                existing["path"],
            )
        else:
            final_path = get_folder_compare_service().safe_replace_directory(staged_root, existing["path"])

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
            await asyncio.to_thread(shutil.copytree, source_path, staged_dir)
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
            final_path = compare_service.apply_merge(
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
            if existing_path:
                manager._notify_index_self_mutation_delete(library, existing_path)
            manager._notify_index_self_mutation_upsert_subtree(library, final_path)
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
            raise FileNotFoundError("New source does not exist")

        if os.path.isfile(source_path):
            staged_archive_path = os.path.join(workspace, os.path.basename(source_path))
            await asyncio.to_thread(shutil.copy2, source_path, staged_archive_path)
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
            await asyncio.to_thread(shutil.copytree, source_path, staged_root)

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
            await asyncio.to_thread(os.remove, target_path)

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
