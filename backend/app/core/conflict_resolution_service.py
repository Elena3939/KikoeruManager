import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Optional

from ..config.settings import get_config
from ..core.extract_service import ExtractService
from ..core.filter_service import FilterService
from ..core.folder_compare_service import get_folder_compare_service
from ..core.library_manager import get_library_manager
from ..core.task_engine import Task, TaskType

logger = logging.getLogger(__name__)


@dataclass
class ConflictMergeSession:
    id: str
    conflict_id: str
    workspace: str
    staged_root: str
    existing_path: str
    existing_library_id: Optional[str]
    existing_library_type: str
    compare_items: list[dict[str, Any]]
    created_at: float


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

        return {
            "library_id": None,
            "library_type": "local",
            "library_name": "",
            "path": raw_path,
            "is_remote": raw_path.startswith("/"),
        }

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
        for root, dirs, files in os.walk(target_path):
            folder_count += len(dirs)
            file_count += len(files)
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except OSError:
                    continue

        return {
            "exists": True,
            "kind": "folder",
            "size": total_size,
            "created_at": created_at,
            "modified_at": modified_at,
            "file_count": file_count,
            "folder_count": folder_count,
        }

    def describe_conflict(self, conflict) -> dict[str, Any]:
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
                "stats": None if existing_context.get("is_remote") else self._describe_local_path_stats(existing_context.get("path")),
            },
            "source": {
                **source_context,
                "stats": None if source_context.get("is_remote") else self._describe_local_path_stats(source_context.get("path")),
            },
            "new_path_kind": "archive" if os.path.isfile(str(conflict.new_path or "")) else "folder",
            "metadata": metadata,
        }

    def get_available_actions(self, conflict) -> list[str]:
        metadata = dict(conflict.new_metadata or {})
        if str(conflict.conflict_type or "").upper() == "EXTRACT_FAILED":
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
        description = self.describe_conflict(conflict)
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
        description = self.describe_conflict(conflict)
        existing = description["existing"]
        if not existing["path"]:
            raise RuntimeError("Missing existing target path")
        if not conflict.new_path:
            raise RuntimeError("Missing new source path")

        self.cleanup_conflict_sessions(conflict.id)
        workspace = self._create_workspace(conflict.id)
        staged_root = await self._stage_new_source(conflict, workspace)
        compare_service = get_folder_compare_service()

        if existing["library_id"] and existing["is_remote"]:
            manager = get_library_manager()
            existing_tree = await manager.folder_contents(existing["library_id"], existing["path"])
            compare_items = compare_service.build_compare_items_from_listing(
                staged_root,
                existing_tree.get("items") or [],
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
        description = self.describe_conflict(conflict)
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

        await self._finalize_new_source(conflict)
        self.cleanup_conflict_sessions(conflict.id)
        return {
            "message": "已采用新版本内容替换现有目录",
            "final_path": final_path,
        }

    async def resolve_skip(self, conflict) -> dict[str, Any]:
        description = self.describe_conflict(conflict)
        source = description["source"]
        await self._delete_source_path(conflict.new_path, source.get("library_id"))
        self.cleanup_conflict_sessions(conflict.id)
        return {
            "message": "已跳过当前压缩包或目录，并删除待处理来源",
            "deleted_path": conflict.new_path,
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

        await self._finalize_new_source(conflict)
        self.cleanup_conflict_sessions(conflict.id)
        return {
            "message": "合并结果已生成并写入目标目录",
            "final_path": final_path,
        }

    def cleanup_conflict_sessions(self, conflict_id: str) -> None:
        target_conflict_id = str(conflict_id or "")
        stale_ids = [
            session_id
            for session_id, session in self._merge_sessions.items()
            if session.conflict_id == target_conflict_id
        ]
        for session_id in stale_ids:
            session = self._merge_sessions.pop(session_id, None)
            if session and os.path.exists(session.workspace):
                shutil.rmtree(session.workspace, ignore_errors=True)

    def _create_workspace(self, conflict_id: str) -> str:
        temp_root = get_config().storage.temp_path
        os.makedirs(temp_root, exist_ok=True)
        return tempfile.mkdtemp(prefix=f"conflict_{conflict_id}_", dir=temp_root)

    async def _stage_new_source(self, conflict, workspace: str) -> str:
        source_path = str(conflict.new_path or "")
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("New source does not exist")

        if os.path.isfile(source_path):
            staged_archive_path = os.path.join(workspace, os.path.basename(source_path))
            shutil.copy2(source_path, staged_archive_path)
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
            shutil.copytree(source_path, staged_root)

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
        await self._delete_source_path(conflict.new_path, source.get("library_id"))

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
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            os.remove(target_path)

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
