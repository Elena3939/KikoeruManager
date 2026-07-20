from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

from ..config.settings import get_config_file_path


logger = logging.getLogger(__name__)

_MANIFEST_VERSION = 1
_MANIFEST_NAME = "manifest.json"


class FilterRecoveryError(RuntimeError):
    pass


class FilterRecoveryConflictError(FilterRecoveryError):
    pass


class FilterRecoveryService:
    """持久化保存过滤项，并负责把它们安全写回最终库存。"""

    def __init__(self, recovery_root: Optional[str] = None) -> None:
        self._recovery_root_override = recovery_root
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def recovery_root(self) -> Path:
        if self._recovery_root_override:
            return Path(self._recovery_root_override).resolve()
        data_path = str(os.environ.get("DATA_PATH") or "").strip()
        if data_path:
            return (Path(data_path).resolve() / "filter-recovery")

        config_path = Path(get_config_file_path()).resolve()
        if config_path.parent.name.lower() == "config":
            parent = config_path.parent.parent
            data_root = parent if parent.name.lower() == "data" else parent / "data"
        else:
            data_root = config_path.parent / "data"
        return data_root / "filter-recovery"

    def capture_item(
        self,
        task_id: str,
        source_path: str,
        *,
        relative_path: str,
        entry_type: str,
        size: int,
    ) -> Dict[str, Any]:
        normalized_task_id = self._validate_token(task_id, "任务 ID")
        source = Path(source_path)
        if not source.exists():
            raise FilterRecoveryError(f"过滤来源不存在: {source_path}")

        safe_relative = self._normalize_relative_path(relative_path)
        recovery_id = uuid.uuid4().hex
        item_root = self._task_root(normalized_task_id) / "payload" / recovery_id
        payload = item_root / source.name
        staged = item_root.with_name(f"{item_root.name}.part")
        item_root.parent.mkdir(parents=True, exist_ok=True)
        self._remove_path(staged, missing_ok=True)

        try:
            staged.mkdir(parents=True, exist_ok=False)
            staged_payload = staged / source.name
            self._move_to_recovery(source, staged_payload, expected_size=max(0, int(size or 0)))
            os.replace(staged, item_root)
        except Exception:
            staged_payload = staged / source.name
            keep_staged = False
            if staged_payload.exists() and not source.exists():
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    self._move_to_recovery(staged_payload, source, expected_size=max(0, int(size or 0)))
                except Exception:
                    keep_staged = True
                    logger.error(
                        "恢复区发布失败且无法回滚过滤来源: task_id=%s source=%s staged=%s",
                        normalized_task_id,
                        source,
                        staged_payload,
                        exc_info=True,
                    )
            if not keep_staged:
                self._remove_path(staged, missing_ok=True)
            raise

        try:
            manifest = self._read_manifest(normalized_task_id, required=False)
            item = {
                "recovery_id": recovery_id,
                "relative_path": safe_relative,
                "restore_relative_path": safe_relative,
                "name": source.name,
                "type": "dir" if entry_type == "dir" else "file",
                "size": max(0, int(size or 0)),
                "recovery_status": "available",
                "restored_at": "",
                "restored_path": "",
            }
            manifest["items"].append(item)
            self._write_manifest(normalized_task_id, manifest)
        except Exception:
            keep_item_root = False
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                self._move_to_recovery(payload, source, expected_size=max(0, int(size or 0)))
            except Exception:
                keep_item_root = True
                logger.error(
                    "恢复清单写入失败且无法回滚过滤来源: task_id=%s source=%s payload=%s",
                    normalized_task_id,
                    source,
                    payload,
                    exc_info=True,
                )
            if not keep_item_root:
                self._remove_path(item_root, missing_ok=True)
            raise
        return dict(item)

    def begin_capture(self, task_id: str) -> None:
        """同一任务重新执行过滤时先清掉上一次未完成尝试。"""
        self.cleanup_task(task_id, strict=True)

    def finalize_task(
        self,
        task_id: str,
        *,
        final_root: str,
        library_id: str = "",
        path_transforms: Optional[list[dict[str, str]]] = None,
    ) -> list[Dict[str, Any]]:
        normalized_task_id = self._validate_token(task_id, "任务 ID")
        manifest = self._read_manifest(normalized_task_id, required=False)
        if not manifest.get("items"):
            return []

        transforms = list(path_transforms or [])
        for item in manifest["items"]:
            item["restore_relative_path"] = self.apply_path_transforms(
                str(item.get("relative_path") or ""),
                transforms,
            )
        manifest["target"] = {
            "ready": bool(str(final_root or "").strip()),
            "root": str(final_root or "").strip(),
            "library_id": str(library_id or "").strip(),
        }
        self._write_manifest(normalized_task_id, manifest)
        return [dict(item) for item in manifest["items"]]

    @staticmethod
    def apply_path_transforms(relative_path: str, transforms: list[dict[str, str]]) -> str:
        current = FilterRecoveryService._normalize_relative_path(relative_path)
        for transform in transforms:
            parent = FilterRecoveryService._normalize_optional_relative_path(
                str(transform.get("parent_relative_path") or "")
            )
            removed = str(transform.get("removed_segment") or "").strip().replace("\\", "/")
            if not removed or "/" in removed or removed in {".", ".."}:
                continue
            prefix = f"{parent}/{removed}" if parent else removed
            if current == prefix:
                current = parent
            elif current.startswith(f"{prefix}/"):
                suffix = current[len(prefix) + 1:]
                current = f"{parent}/{suffix}" if parent else suffix
        return FilterRecoveryService._normalize_relative_path(current)

    async def restore_item(self, item_id: str, recovery_id: str) -> Dict[str, Any]:
        task_id = self._task_id_from_item_id(item_id)
        normalized_recovery_id = self._validate_token(recovery_id, "恢复 ID")
        lock = self._task_lock(task_id)
        acquired = await asyncio.to_thread(lock.acquire, False)
        if not acquired:
            raise FilterRecoveryConflictError("该任务已有文件正在还原")
        try:
            return await self._restore_item_locked(task_id, normalized_recovery_id)
        finally:
            lock.release()

    async def _restore_item_locked(self, task_id: str, recovery_id: str) -> Dict[str, Any]:
        from ..models.database import SessionLocal, Task as TaskRecord
        from .library_manager import get_library_manager
        from .task_engine import TaskStatus, get_task_engine

        engine = get_task_engine()
        live_task = engine.get_task(task_id)
        db = SessionLocal()
        activity_item: Dict[str, Any] = {"recovery_id": recovery_id}
        try:
            record = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            if live_task is None and record is None:
                raise FilterRecoveryError("任务记录不存在")
            status = (
                live_task.status.value
                if live_task is not None and hasattr(live_task.status, "value")
                else str(getattr(record, "status", "") or "")
            )
            if status not in {TaskStatus.COMPLETED.value, TaskStatus.WAITING_MANUAL.value}:
                raise FilterRecoveryError("任务尚未完成，当前不能还原过滤项")

            manifest = self._read_manifest(task_id)
            item = next(
                (entry for entry in manifest.get("items") or [] if entry.get("recovery_id") == recovery_id),
                None,
            )
            if item is None:
                raise FilterRecoveryError("恢复项不存在或不属于该任务")
            activity_item = item
            if item.get("recovery_status") == "restored":
                raise FilterRecoveryConflictError("该文件已经还原")

            target = dict(manifest.get("target") or {})
            if not target.get("ready") or not str(target.get("root") or "").strip():
                raise FilterRecoveryError("任务尚未确定最终入库位置")

            payload = self._payload_path(task_id, item)
            if not payload.exists():
                item["recovery_status"] = "missing"
                self._write_manifest(task_id, manifest)
                self._sync_task_metadata(engine, live_task, record, db, manifest)
                raise FilterRecoveryError("恢复内容已经丢失")

            manager = get_library_manager()
            library_id = str(target.get("library_id") or "").strip()
            library = manager.get_library_definition(library_id) if library_id else None
            target_root_text = str(target.get("root") or "").strip()
            target_is_local_staging = bool(target_root_text and os.path.exists(target_root_text))
            if library is not None and library.type != "local" and not target_is_local_staging:
                restored_path = await self._restore_remote(manager, library, payload, target, item)
            else:
                restored_path = await asyncio.to_thread(self._restore_local, payload, target, item)

            restored_at = datetime.now().isoformat()
            item["recovery_status"] = "restored"
            item["restored_at"] = restored_at
            item["restored_path"] = restored_path
            try:
                self._write_manifest(task_id, manifest)
                self._sync_task_metadata(engine, live_task, record, db, manifest)
            except Exception:
                if not payload.exists():
                    try:
                        restored = Path(restored_path)
                        payload.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(restored, payload)
                    except Exception:
                        logger.error(
                            "还原状态持久化失败且无法回滚本地内容: task_id=%s recovery_id=%s",
                            task_id,
                            recovery_id,
                            exc_info=True,
                        )
                item["recovery_status"] = "available"
                item["restored_at"] = ""
                item["restored_path"] = ""
                try:
                    self._write_manifest(task_id, manifest)
                except Exception:
                    logger.error("回滚过滤恢复清单失败: task_id=%s", task_id, exc_info=True)
                raise
            try:
                self._remove_path(payload.parent, missing_ok=True)
            except Exception:
                logger.warning(
                    "还原成功后清理恢复 payload 失败: task_id=%s recovery_id=%s",
                    task_id,
                    recovery_id,
                    exc_info=True,
                )
            self._notify_library_index(manager, library, restored_path)
            self._write_activity(task_id, item, restored_path, status="success")
            return {
                "success": True,
                "message": f"已还原 {item.get('name') or '过滤项'}",
                "recovery_id": recovery_id,
                "recovery_status": "restored",
                "restored_path": restored_path,
                "restored_at": restored_at,
            }
        except Exception as exc:
            self._write_activity(task_id, activity_item, "", status="error", error=str(exc))
            raise
        finally:
            db.close()

    def cleanup_task(self, task_id: str, *, strict: bool = True) -> bool:
        normalized_task_id = self._validate_token(task_id, "任务 ID")
        task_root = self._task_root(normalized_task_id)
        if not task_root.exists():
            return True
        try:
            shutil.rmtree(task_root)
            return True
        except Exception as exc:
            logger.warning("清理过滤恢复数据失败: task_id=%s error=%s", task_id, exc, exc_info=True)
            if strict:
                raise FilterRecoveryError(f"清理任务恢复数据失败: {exc}") from exc
            return False

    def _restore_local(self, payload: Path, target: Dict[str, Any], item: Dict[str, Any]) -> str:
        root = Path(str(target.get("root") or "")).resolve()
        relative = self._normalize_relative_path(str(item.get("restore_relative_path") or ""))
        destination = (root / Path(relative)).resolve()
        self._assert_inside(root, destination)
        if destination.exists():
            raise FilterRecoveryConflictError(f"目标已存在同名内容: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(payload, destination)
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EACCES, errno.EPERM}:
                raise
            try:
                if payload.is_dir():
                    shutil.copytree(payload, destination, copy_function=shutil.copy2)
                else:
                    shutil.copy2(payload, destination)
            except Exception:
                self._remove_path(destination, missing_ok=True)
                raise
        return str(destination)

    async def _restore_remote(self, manager: Any, library: Any, payload: Path, target: Dict[str, Any], item: Dict[str, Any]) -> str:
        relative = self._normalize_relative_path(str(item.get("restore_relative_path") or ""))
        remote_root = PurePosixPath(str(target.get("root") or "/"))
        destination = PurePosixPath(remote_root, relative)
        client = manager.get_cached_synology_client(library.synology)
        normalized_destination = manager._normalize_remote_path(str(destination))
        if await manager._remote_path_exists(client, normalized_destination):
            raise FilterRecoveryConflictError(f"目标已存在同名内容: {normalized_destination}")

        parent_relative = str(PurePosixPath(relative).parent)
        if parent_relative == ".":
            parent_relative = ""
        relative_target_dir = str(PurePosixPath(str(remote_root), parent_relative))
        library_relative_target = str(PurePosixPath(relative_target_dir).relative_to(PurePosixPath(library.root_path)))
        if library_relative_target == ".":
            library_relative_target = ""
        restored_path = await manager.upload_directory_to_library(
            library.id,
            str(payload),
            library_relative_target,
            delete_source_on_success=False,
        )
        return str(restored_path)

    def _sync_task_metadata(self, engine: Any, live_task: Any, record: Any, db: Any, manifest: Dict[str, Any]) -> None:
        def merge(metadata: Dict[str, Any]) -> Dict[str, Any]:
            updated = dict(metadata or {})
            by_id = {str(entry.get("recovery_id") or ""): entry for entry in manifest.get("items") or []}
            filtered_items = []
            for current in updated.get("filtered_items") or []:
                recovery = by_id.get(str(current.get("recovery_id") or ""))
                filtered_items.append({**current, **recovery} if recovery else current)
            updated["filtered_items"] = filtered_items
            updated["filter_recovery"] = self._public_summary(manifest)
            return updated

        if live_task is not None:
            live_task.task_metadata = merge(dict(live_task.task_metadata or {}))
            live_task.touch_metadata("filtered_item_restored")
            engine.persist_task_snapshot(live_task)
            return
        record.task_metadata = merge(dict(record.task_metadata or {}))
        updated_metadata = dict(record.task_metadata or {})
        try:
            from ..models.database import TaskCenterItem

            materialized = db.query(TaskCenterItem).filter(TaskCenterItem.engine_task_id == record.id).first()
            if materialized is not None:
                payload = dict(materialized.payload_json or {})
                details = dict(payload.get("details") or {})
                details["metadata"] = updated_metadata
                payload["details"] = details
                materialized.payload_json = payload
                materialized.updated_at = datetime.now()
        except Exception:
            logger.warning("更新过滤恢复任务物化快照失败: task_id=%s", record.id, exc_info=True)
        db.commit()
        try:
            from .realtime_event_service import broadcast_event

            broadcast_event({
                "type": "task.center.changed",
                "reason": "filtered_item_restored",
                "id": f"engine:{record.id}",
                "domain": "import",
                "status": str(record.status or ""),
                "progress": int(record.progress or 0),
                "current_step": str(record.current_step or ""),
                "payload": {"engine_task_id": record.id},
            })
        except Exception:
            logger.debug("广播过滤恢复任务变更失败: task_id=%s", record.id, exc_info=True)

    @staticmethod
    def _notify_library_index(manager: Any, library: Any, restored_path: str) -> None:
        if library is None:
            return
        try:
            manager._notify_index_self_mutation_upsert_subtree(library, restored_path)
        except Exception:
            logger.warning("还原后通知库存索引失败: path=%s", restored_path, exc_info=True)

    @staticmethod
    def _write_activity(task_id: str, item: Dict[str, Any], restored_path: str, *, status: str, error: str = "") -> None:
        try:
            from .activity_log_service import write_activity_log

            name = str(item.get("name") or item.get("recovery_id") or "过滤项")
            summary = f"还原过滤项：{name}" if status == "success" else f"还原过滤项失败：{name}"
            write_activity_log(
                category="auto_import",
                action="filtered_item_restore",
                status=status,
                summary=summary,
                detail={
                    "source_page": "tasks",
                    "source_action": "filtered_item_restore",
                    "recovery_id": item.get("recovery_id"),
                    "relative_path": item.get("restore_relative_path") or item.get("relative_path"),
                    "entry_type": item.get("type"),
                    "restored_path": restored_path,
                    "error": error,
                },
                task_id=task_id,
                source_path=restored_path or None,
            )
        except Exception:
            logger.warning("记录过滤项还原操作失败: task_id=%s", task_id, exc_info=True)

    def _move_to_recovery(self, source: Path, destination: Path, *, expected_size: int) -> None:
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EACCES, errno.EPERM}:
                raise

        if source.is_dir():
            shutil.copytree(source, destination, copy_function=shutil.copy2)
            copied_size = self._path_size(destination)
            if expected_size and copied_size != expected_size:
                raise FilterRecoveryError(f"跨盘复制校验失败: {copied_size} != {expected_size}")
            shutil.rmtree(source)
        else:
            shutil.copy2(source, destination)
            copied_size = destination.stat().st_size
            if expected_size and copied_size != expected_size:
                raise FilterRecoveryError(f"跨盘复制校验失败: {copied_size} != {expected_size}")
            source.unlink()

    def _read_manifest(self, task_id: str, *, required: bool = True) -> Dict[str, Any]:
        path = self._manifest_path(task_id)
        if not path.exists():
            if required:
                raise FilterRecoveryError("该任务没有可用的过滤恢复数据")
            return {"version": _MANIFEST_VERSION, "task_id": task_id, "target": {}, "items": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FilterRecoveryError(f"读取过滤恢复清单失败: {exc}") from exc
        if payload.get("task_id") != task_id or not isinstance(payload.get("items"), list):
            raise FilterRecoveryError("过滤恢复清单格式无效")
        return payload

    def _write_manifest(self, task_id: str, manifest: Dict[str, Any]) -> None:
        task_root = self._task_root(task_id)
        task_root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": _MANIFEST_VERSION,
            "task_id": task_id,
            "target": dict(manifest.get("target") or {}),
            "items": list(manifest.get("items") or []),
        }
        target = self._manifest_path(task_id)
        temp = target.with_suffix(f".tmp-{uuid.uuid4().hex}")
        try:
            temp.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)

    def public_summary(self, task_id: str) -> Dict[str, Any]:
        manifest = self._read_manifest(task_id, required=False)
        return self._public_summary(manifest)

    @staticmethod
    def _public_summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
        items = list(manifest.get("items") or [])
        return {
            "version": _MANIFEST_VERSION,
            "target_ready": bool((manifest.get("target") or {}).get("ready")),
            "available_count": sum(1 for item in items if item.get("recovery_status") == "available"),
            "restored_count": sum(1 for item in items if item.get("recovery_status") == "restored"),
            "missing_count": sum(1 for item in items if item.get("recovery_status") == "missing"),
        }

    def _payload_path(self, task_id: str, item: Dict[str, Any]) -> Path:
        recovery_id = self._validate_token(str(item.get("recovery_id") or ""), "恢复 ID")
        name = Path(str(item.get("name") or "")).name
        if not name:
            raise FilterRecoveryError("恢复项文件名无效")
        item_root = (self._task_root(task_id) / "payload" / recovery_id).resolve()
        payload = (item_root / name).resolve()
        self._assert_inside(item_root, payload)
        return payload

    def _task_root(self, task_id: str) -> Path:
        task_id = self._validate_token(task_id, "任务 ID")
        root = self.recovery_root()
        task_root = (root / task_id).resolve()
        self._assert_inside(root.resolve(), task_root)
        return task_root

    def _manifest_path(self, task_id: str) -> Path:
        return self._task_root(task_id) / _MANIFEST_NAME

    def _task_lock(self, task_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(task_id, threading.Lock())

    @staticmethod
    def _task_id_from_item_id(item_id: str) -> str:
        normalized = str(item_id or "").strip()
        if not normalized.startswith("engine:"):
            raise FilterRecoveryError("仅解压入库任务支持还原过滤项")
        return FilterRecoveryService._validate_token(normalized.split(":", 1)[1], "任务 ID")

    @staticmethod
    def _validate_token(value: str, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in normalized):
            raise FilterRecoveryError(f"{label}无效")
        return normalized

    @staticmethod
    def _normalize_relative_path(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip("/")
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        if not parts or any(part == ".." for part in parts):
            raise FilterRecoveryError("恢复相对路径无效")
        return "/".join(parts)

    @staticmethod
    def _normalize_optional_relative_path(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip("/")
        if not normalized:
            return ""
        return FilterRecoveryService._normalize_relative_path(normalized)

    @staticmethod
    def _assert_inside(root: Path, target: Path) -> None:
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise FilterRecoveryError("恢复路径超出允许范围") from exc

    @staticmethod
    def _path_size(path: Path) -> int:
        if path.is_file():
            return int(path.stat().st_size)
        total = 0
        for root, _, files in os.walk(path):
            for file in files:
                total += int((Path(root) / file).stat().st_size)
        return total

    @staticmethod
    def _remove_path(path: Path, *, missing_ok: bool) -> None:
        if not path.exists():
            if missing_ok:
                return
            raise FileNotFoundError(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


_filter_recovery_service: Optional[FilterRecoveryService] = None


def get_filter_recovery_service() -> FilterRecoveryService:
    global _filter_recovery_service
    if _filter_recovery_service is None:
        _filter_recovery_service = FilterRecoveryService()
    return _filter_recovery_service
