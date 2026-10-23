"""库存 API 重命名失败的登记和原地重试，不复用导入流水线。"""

import os
import logging
from pathlib import PurePosixPath

from .import_validation import ImportDataError

logger = logging.getLogger(__name__)


def notify_api_rename_problem_changed() -> None:
    from .realtime_event_service import broadcast_event

    broadcast_event({"type": "conflict.changed", "reason": "api_rename", "domain": "conflicts"})


def resolve_api_rename_successes(items: list[dict], *, batch_id: str = "") -> list[str]:
    """按库存和重命名前路径关闭失败项；同 RJ 的其它位置与其它业务互不影响。"""
    from sqlalchemy import and_, or_
    from ..models.database import ConflictWork, get_db

    succeeded = {
        (str(item.get("library_id") or ""), str(item.get("path") or "")): item
        for item in items
        if item.get("success") and item.get("library_id") and item.get("path")
    }
    if not succeeded:
        return []
    paths_by_library: dict[str, list[str]] = {}
    for library_id, path in succeeded:
        paths_by_library.setdefault(library_id, []).append(path)

    db = next(get_db())
    resolved = []
    try:
        conflicts = db.query(ConflictWork).filter(
            ConflictWork.conflict_type == "PROCESS_FAILED",
            ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            ConflictWork.new_metadata["source_operation"].as_string() == "api_rename",
            or_(*(
                and_(
                    ConflictWork.new_metadata["library_id"].as_string() == library_id,
                    ConflictWork.new_path.in_(paths),
                )
                for library_id, paths in paths_by_library.items()
            )),
        ).all()
        for conflict in conflicts:
            metadata = dict(conflict.new_metadata or {})
            item = succeeded.get((str(metadata.get("library_id") or ""), conflict.new_path))
            if not item or metadata.get("source_operation") != "api_rename":
                continue
            resolved.append({
                "conflict_id": str(conflict.id),
                "rjcode": conflict.rjcode,
                "source_path": conflict.new_path,
                "final_path": item.get("new_path") or conflict.new_path,
                "extra_detail": {
                    "source_operation": "api_rename",
                    "resolution_source": "library",
                    "library_id": metadata["library_id"],
                    "batch_id": batch_id,
                    "original_failure_reason": metadata.get("error_message") or "",
                },
            })
            db.delete(conflict)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("库存 API 重命名成功后同步问题作品失败")
        return []
    finally:
        db.close()

    for entry in resolved:
        try:
            from .activity_log_service import log_conflict_resolution_activity
            log_conflict_resolution_activity(action="RETRY", status="success", **entry)
        except Exception:
            logger.exception("记录库存 API 重命名恢复问题作品失败")
    if resolved:
        notify_api_rename_problem_changed()
    return [entry["conflict_id"] for entry in resolved]


def record_api_rename_failure(library_id: str, path: str, rjcode: str, reason: str, *, stage: str = "rename") -> None:
    from .classifier import SmartClassifier
    from .library_manager import get_library_manager
    from .task_engine import TaskType

    if not library_id or not path or not rjcode:
        return
    manager = get_library_manager()
    library = manager.get_library_definition(library_id)
    # 只登记通过库存边界校验的作品，不把非法请求变成可执行的重试任务。
    if library.type == "local":
        manager._assert_local_path_in_library(library, path)
    else:
        manager._resolve_remote_operation_path(library, path, action="API 重命名失败登记")
    SmartClassifier()._add_to_conflict_works(
        None, rjcode, "PROCESS_FAILED", "", path,
        {
            "rjcode": rjcode,
            "source_operation": "api_rename",
            "source_task_type": TaskType.RENAME.value,
            "library_id": library_id,
            "source_library_type": library.type,
            "failure_stage": stage,
            "retry_source_path": path,
            "error_message": reason,
            "available_actions": ["RETRY", "SKIP"],
        },
        status="PENDING",
    )


async def retry_api_rename(task) -> str:
    from .library_manager import get_library_manager
    from .metadata_service import MetadataService
    from .rename_service import RenameService
    from .import_validation import api_rename_metadata_skip_reason

    manager = get_library_manager()
    library_id = task.task_metadata["library_id"]
    library = manager.get_library_definition(library_id)
    task.update_progress(20, "重新获取 API 重命名元数据")
    task.task_metadata["failure_stage"] = "metadata"
    metadata = await MetadataService().fetch(task.source_path, task, force_refresh=True)
    reason = api_rename_metadata_skip_reason(metadata, task.rjcode)
    if reason:
        raise ImportDataError(reason)
    service = RenameService()
    japanese = None
    if service.config.rename.use_japanese_metadata:
        japanese = await service._get_japanese_metadata(task.rjcode)
        if not japanese:
            raise ImportDataError("日语元数据获取失败，已停止重命名")
    name = service._sanitize_filename(service._compile_name(metadata, japanese))
    path = task.source_path
    old_name = PurePosixPath(path).name if library.type != "local" else os.path.basename(path)
    task.task_metadata["failure_stage"] = "rename"
    task.update_progress(70, "原地重命名库存作品")
    if name == old_name:
        return path
    result = await manager.rename(library_id, path, name, sync_index_mutation=True)
    return result["new_path"]
