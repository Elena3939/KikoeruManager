"""低优先级、可恢复的源压缩包归档队列。"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import errno
import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError

from ..config.settings import get_config
from ..models.database import DeferredArchiveJob, ProcessedArchive, SessionLocal, Task as TaskRecord, get_local_now
from .archive_volume_utils import detect_archive_volume_group, get_archive_volume_paths, sort_archive_volumes
from .resource_budget_service import get_resource_budget_service

logger = logging.getLogger(__name__)

# failed 也继续占有源文件。已经成功入库的文件不能因为归档最终失败又被 watcher 重复入库。
_ACTIVE_STATUSES = {"pending", "processing", "waiting_retry"}
_CLAIM_STATUSES = _ACTIVE_STATUSES | {"failed"}
_READY_STATUSES = {"pending", "waiting_retry"}
_LEASE_SECONDS = 90
_HEARTBEAT_SECONDS = 20
_STOP_GRACE_SECONDS = 35
_COPY_BUFFER_SIZE = 8 * 1024 * 1024
_CONTROL_CHECK_CHUNKS = 8
_STAGING_DIRECTORY = ".kikoerumanager_archive_staging"


class _YieldToForeground(RuntimeError):
    """普通业务任务到来，归档在安全复制边界主动让路。"""


class _ArchiveCancelled(RuntimeError):
    """归档在未发布任何成员前被取消。"""


class _LeaseLost(RuntimeError):
    """归档 worker 的租约已被其他 worker 接管。"""


class _ShutdownRequested(RuntimeError):
    """服务关闭，当前成员在安全边界停止。"""


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(str(value or "")))


def _rjcode_from_value(value: str) -> str:
    import re

    matched = re.search(r"RJ\d{4,}", str(value or ""), re.IGNORECASE)
    return matched.group(0).upper() if matched else ""


class DeferredArchiveService:
    """把源压缩包搬运从业务主链摘出，只在系统空闲时以单 worker 运行。"""

    def __init__(self) -> None:
        self._owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:10]}"
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._idle_since: Optional[float] = None
        self._claimed_paths: set[str] = set()
        self._claims_lock = threading.RLock()
        self._control_lock = threading.RLock()
        self._active_job_id = ""
        self._active_abort_reason = ""
        self._active_copy_running = False
        self._active_interrupt = threading.Event()

    @staticmethod
    def _processing_config() -> Any:
        return getattr(get_config(), "processing", None)

    def _idle_delay_seconds(self) -> float:
        cfg = self._processing_config()
        return max(0.0, float(getattr(cfg, "archive_idle_delay_seconds", 60) or 60))

    def _poll_interval_seconds(self) -> float:
        cfg = self._processing_config()
        return max(0.5, float(getattr(cfg, "archive_poll_interval_seconds", 3) or 3))

    def _retry_delay_seconds(self) -> int:
        cfg = self._processing_config()
        return max(5, int(getattr(cfg, "archive_retry_delay_seconds", 300) or 300))

    def _max_retry_count(self) -> int:
        cfg = self._processing_config()
        return max(1, int(getattr(cfg, "archive_max_retry_count", 5) or 5))

    def _set_active_job(self, job_id: str) -> None:
        with self._control_lock:
            self._active_job_id = str(job_id or "")
            self._active_abort_reason = ""
            self._active_interrupt.clear()

    def _clear_active_job(self, job_id: str) -> None:
        with self._control_lock:
            if self._active_job_id == str(job_id or ""):
                self._active_job_id = ""
                self._active_abort_reason = ""
                self._active_interrupt.clear()
                self._active_copy_running = False

    def _request_active_abort(self, job_id: str, reason: str) -> None:
        with self._control_lock:
            if self._active_job_id != str(job_id or ""):
                return
            self._active_abort_reason = str(reason or "shutdown")
            self._active_interrupt.set()

    def _active_abort_reason_for(self, job_id: str) -> str:
        with self._control_lock:
            if self._active_job_id != str(job_id or ""):
                return ""
            return self._active_abort_reason if self._active_interrupt.is_set() else ""

    def _set_copy_running(self, running: bool) -> None:
        with self._control_lock:
            self._active_copy_running = bool(running)

    def _is_copy_running(self) -> bool:
        with self._control_lock:
            return bool(self._active_copy_running)

    def _add_claims(self, manifest: list[dict[str, Any]]) -> None:
        with self._claims_lock:
            for item in manifest or []:
                path = str((item or {}).get("source_path") or "").strip()
                if path:
                    self._claimed_paths.add(_normalized_path(path))

    def _remove_claims(self, manifest: list[dict[str, Any]]) -> None:
        with self._claims_lock:
            for item in manifest or []:
                path = str((item or {}).get("source_path") or "").strip()
                if path:
                    self._claimed_paths.discard(_normalized_path(path))

    def refresh_claims_sync(self) -> int:
        with self._claims_lock:
            db = SessionLocal()
            try:
                rows = db.query(DeferredArchiveJob.source_manifest).filter(
                    DeferredArchiveJob.status.in_(sorted(_CLAIM_STATUSES))
                ).all()
                claims: set[str] = set()
                for (manifest,) in rows:
                    for item in list(manifest or []):
                        path = str((item or {}).get("source_path") or "").strip()
                        if path:
                            claims.add(_normalized_path(path))
                self._claimed_paths = claims
                return len(claims)
            finally:
                db.close()

    def is_source_claimed_sync(self, source_path: str) -> bool:
        normalized = _normalized_path(source_path)
        if not normalized:
            return False
        # 文件 watcher 与批量扫描可能运行在其他进程；本地集合只能减少重复写入，
        # 不能作为跨进程声明的正确性来源。每次查询都以持久化状态为准。
        try:
            self.refresh_claims_sync()
            with self._claims_lock:
                return normalized in self._claimed_paths
        except Exception:
            # 删除和重入的判断失败时宁可保留源文件；调用方会据此跳过破坏性操作。
            logger.warning("[延后归档] 查询源文件声明失败 path=%s", source_path, exc_info=True)
            return True

    async def is_source_claimed(self, source_path: str) -> bool:
        return await asyncio.to_thread(self.is_source_claimed_sync, source_path)

    def active_target_paths_sync(self) -> set[str]:
        """返回尚未完成归档作业预留/已发布的目标路径。

        ``ProcessedArchive`` 只应描述完整归档。扫描和清理路径必须跳过这些
        目标，避免把分卷组的中间发布状态误当成可清理的已处理压缩包。
        """
        db = SessionLocal()
        try:
            rows = db.query(DeferredArchiveJob.target_manifest).filter(
                ~DeferredArchiveJob.status.in_(["completed", "cancelled"])
            ).all()
            paths: set[str] = set()
            for (manifest,) in rows:
                paths.update(self._manifest_paths(manifest, "target_path"))
            return paths
        finally:
            db.close()

    def is_target_claimed_sync(self, target_path: str) -> bool:
        normalized = _normalized_path(target_path)
        if not normalized:
            return False
        try:
            return normalized in self.active_target_paths_sync()
        except Exception:
            # 清理路径查询失败时宁可保留文件，不能删除仍可用于恢复的目标副本。
            logger.warning("[延后归档] 查询目标文件声明失败 path=%s", target_path, exc_info=True)
            return True

    @staticmethod
    def _identity_from_stat(stat_result: os.stat_result) -> dict[str, int]:
        return {
            "size": int(stat_result.st_size),
            "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            "ctime_ns": int(getattr(stat_result, "st_ctime_ns", int(stat_result.st_ctime * 1_000_000_000))),
            "device": int(getattr(stat_result, "st_dev", 0) or 0),
            "inode": int(getattr(stat_result, "st_ino", 0) or 0),
        }

    def _build_source_manifest(self, source_path: str) -> tuple[list[dict[str, Any]], str]:
        normalized_source = os.path.abspath(str(source_path or ""))
        if not normalized_source or not os.path.isfile(normalized_source):
            raise FileNotFoundError(f"源压缩包不存在: {source_path}")
        paths = sort_archive_volumes(get_archive_volume_paths(normalized_source))
        group = detect_archive_volume_group(normalized_source)
        group_base = str(getattr(group, "base_name", "") or "")
        manifest: list[dict[str, Any]] = []
        for path in paths:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"分卷不存在: {path}")
            stat_result = os.stat(path)
            manifest.append({
                "source_path": os.path.abspath(path),
                "filename": os.path.basename(path),
                **self._identity_from_stat(stat_result),
            })
        return manifest, group_base

    @staticmethod
    def _manifest_key(manifest: list[dict[str, Any]], processed_dir: str) -> str:
        payload = {
            "processed_dir": _normalized_path(processed_dir),
            "sources": [
                {
                    "path": _normalized_path(item.get("source_path") or ""),
                    "size": int(item.get("size") or 0),
                    "mtime_ns": int(item.get("mtime_ns") or 0),
                    "ctime_ns": int(item.get("ctime_ns") or 0),
                    "device": int(item.get("device") or 0),
                    "inode": int(item.get("inode") or 0),
                }
                for item in manifest
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()

    @staticmethod
    def _target_name(filename: str, group_base: str, suffix: int) -> str:
        if suffix <= 0:
            return filename
        marker = f" ({suffix})"
        if group_base and filename.casefold().startswith(group_base.casefold()):
            return f"{group_base}{marker}{filename[len(group_base):]}"
        stem, extension = os.path.splitext(filename)
        return f"{stem}{marker}{extension}"

    @staticmethod
    def _manifest_paths(manifest: Any, key: str) -> set[str]:
        return {
            _normalized_path(str((item or {}).get(key) or ""))
            for item in list(manifest or [])
            if str((item or {}).get(key) or "").strip()
        }

    def _reserve_targets_sync(
        self,
        db: Any,
        *,
        source_manifest: list[dict[str, Any]],
        processed_dir: str,
        group_base: str,
    ) -> list[dict[str, Any]]:
        reserved: set[str] = set()
        rows = db.query(DeferredArchiveJob.target_manifest).filter(
            ~DeferredArchiveJob.status.in_(["completed", "cancelled"])
        ).all()
        for (manifest,) in rows:
            reserved.update(self._manifest_paths(manifest, "target_path"))

        for suffix in range(0, 10000):
            targets: list[dict[str, Any]] = []
            collision = False
            for item in source_manifest:
                filename = self._target_name(str(item["filename"]), group_base, suffix)
                target_path = os.path.join(processed_dir, filename)
                if _normalized_path(target_path) in reserved or os.path.exists(target_path):
                    collision = True
                    break
                targets.append({
                    "source_path": item["source_path"],
                    "filename": filename,
                    "target_path": target_path,
                    "size": int(item["size"]),
                    "state": "pending",
                    "sha256": "",
                })
            if not collision:
                return targets
        raise RuntimeError("无法为归档分卷预留目标文件名")

    @staticmethod
    def _database_now(db: Any) -> datetime:
        value = db.execute(text("SELECT CURRENT_TIMESTAMP")).scalar()
        return value if isinstance(value, datetime) else get_local_now()

    def _existing_job_response(self, job: DeferredArchiveJob) -> dict[str, Any]:
        return {
            "queued": str(job.status or "") in _ACTIVE_STATUSES,
            "replayed": True,
            "job_id": str(job.id or ""),
            "status": str(job.status or ""),
            "volume_count": len(job.source_manifest or []),
            "last_error": str(job.last_error or ""),
        }

    def enqueue_sync(
        self,
        source_path: str,
        *,
        task_id: str = "",
        rjcode: str = "",
    ) -> dict[str, Any]:
        config = get_config()
        processed_dir = os.path.abspath(str(getattr(config.storage, "processed_archives_path", "") or ""))
        normalized_source = os.path.abspath(str(source_path or ""))
        if not processed_dir:
            raise RuntimeError("未配置已处理压缩包目录")
        if _normalized_path(normalized_source).startswith(_normalized_path(processed_dir) + os.sep):
            return {"queued": False, "status": "skipped", "reason": "source_already_in_processed"}

        source_manifest, group_base = self._build_source_manifest(normalized_source)
        idempotency_key = self._manifest_key(source_manifest, processed_dir)
        source_paths = self._manifest_paths(source_manifest, "source_path")
        db = SessionLocal()
        try:
            # 序列化入队和目标名预留，避免同一分卷组被并发声明两次。
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {
                "key": "kikoerumanager:deferred-archive:enqueue",
            })
            existing = db.query(DeferredArchiveJob).filter(
                DeferredArchiveJob.idempotency_key == idempotency_key
            ).first()
            if existing is not None:
                if str(existing.status or "") in _CLAIM_STATUSES:
                    self._add_claims(list(existing.source_manifest or []))
                return self._existing_job_response(existing)

            nonterminal = db.query(DeferredArchiveJob).filter(
                ~DeferredArchiveJob.status.in_(["completed", "cancelled"])
            ).all()
            for job in nonterminal:
                if source_paths & self._manifest_paths(job.source_manifest, "source_path"):
                    # 失败且尚未发布任何成员的旧声明不能永久拦住同路径的新下载。
                    # 已发布过成员则必须继续恢复原作业，避免把分卷组拆成两套目标。
                    if (
                        str(job.status or "") == "failed"
                        and not any(
                            str((item or {}).get("state") or "") != "pending"
                            for item in list(job.target_manifest or [])
                        )
                    ):
                        job.status = "cancelled"
                        job.completed_at = self._database_now(db)
                        job.updated_at = job.completed_at
                        job.lease_owner = None
                        job.lease_until = None
                        continue
                    if str(job.status or "") in _CLAIM_STATUSES:
                        self._add_claims(list(job.source_manifest or []))
                    return self._existing_job_response(job)

            os.makedirs(processed_dir, exist_ok=True)
            target_manifest = self._reserve_targets_sync(
                db,
                source_manifest=source_manifest,
                processed_dir=processed_dir,
                group_base=group_base,
            )
            now = self._database_now(db)
            job = DeferredArchiveJob(
                id=str(uuid.uuid4()),
                idempotency_key=idempotency_key,
                task_id=str(task_id or "").strip() or None,
                rjcode=str(rjcode or _rjcode_from_value(normalized_source)).strip().upper() or None,
                status="pending",
                source_manifest=source_manifest,
                target_manifest=target_manifest,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(job)
            db.commit()
            self._add_claims(source_manifest)
            return {
                "queued": True,
                "replayed": False,
                "job_id": job.id,
                "status": job.status,
                "volume_count": len(source_manifest),
                "last_error": "",
            }
        except IntegrityError:
            # unique idempotency key 的极窄竞争窗口，回读已有作业而不是把入库任务判失败。
            db.rollback()
            existing = db.query(DeferredArchiveJob).filter(
                DeferredArchiveJob.idempotency_key == idempotency_key
            ).first()
            if existing is None:
                raise
            if str(existing.status or "") in _CLAIM_STATUSES:
                self._add_claims(list(existing.source_manifest or []))
            return self._existing_job_response(existing)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def enqueue_task(self, task: Any) -> dict[str, Any]:
        source_path = str(getattr(task, "source_path", "") or "").strip()
        result = await asyncio.to_thread(
            self.enqueue_sync,
            source_path,
            task_id=str(getattr(task, "id", "") or ""),
            rjcode=str(getattr(task, "rjcode", "") or ""),
        )
        if task is not None:
            metadata = dict(getattr(task, "task_metadata", None) or {})
            metadata.update({
                "archive_queue_id": result.get("job_id") or metadata.get("archive_queue_id") or "",
                "archive_queue_status": result.get("status") or ("pending" if result.get("queued") else "skipped"),
                "archive_volume_count": int(result.get("volume_count") or 0),
                "archive_queued_at": datetime.now().isoformat(),
            })
            if result.get("last_error"):
                metadata["archive_last_error"] = str(result["last_error"])
            task.task_metadata = metadata
            touch = getattr(task, "touch_metadata", None)
            if callable(touch):
                touch("archive_queued")
        if result.get("queued"):
            self._write_activity("archive_queued", "pending", result, source_path, task)
        return result

    async def enqueue_source(
        self,
        source_path: str,
        *,
        task_id: str = "",
        rjcode: str = "",
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self.enqueue_sync,
            source_path,
            task_id=task_id,
            rjcode=rjcode,
        )
        if result.get("queued"):
            self._write_activity("archive_queued", "pending", result, source_path, None)
        return result

    async def start(self) -> None:
        self._shutdown = False
        await asyncio.to_thread(self.refresh_claims_sync)
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(), name="deferred-archive-worker")
            logger.info("[延后归档] 空闲归档 worker 已启动 owner=%s", self._owner)

    async def stop(self) -> None:
        self._shutdown = True
        with self._control_lock:
            active_job_id = self._active_job_id
        if active_job_id:
            self._request_active_abort(active_job_id, "shutdown")
        task = self._worker_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=_STOP_GRACE_SECONDS)
            except asyncio.TimeoutError:
                # 不释放 lease：后台复制线程尚未确认停在安全点，强行重新认领会造成双写。
                logger.warning("[延后归档] 关闭等待超时，保留 lease 等待过期恢复 job=%s", active_job_id)
                return
            except asyncio.CancelledError:
                pass
        if not self._is_copy_running():
            await asyncio.to_thread(self._release_owned_jobs_sync)
        self._worker_task = None

    def _has_foreground_work(self) -> bool:
        try:
            from .task_engine import TaskStatus, get_task_engine

            return any(
                task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}
                for task in get_task_engine().get_all_tasks(include_hidden=True)
            )
        except Exception:
            # 无法可靠判断空闲时宁可不归档，不能抢占前台任务资源。
            logger.debug("[延后归档] 判断业务任务空闲状态失败", exc_info=True)
            return True

    async def _worker(self) -> None:
        while not self._shutdown:
            try:
                if self._has_foreground_work():
                    self._idle_since = None
                    await asyncio.sleep(self._poll_interval_seconds())
                    continue
                now = time.monotonic()
                if self._idle_since is None:
                    self._idle_since = now
                remaining = self._idle_delay_seconds() - (now - self._idle_since)
                if remaining > 0:
                    await asyncio.sleep(min(self._poll_interval_seconds(), remaining))
                    continue
                claim = await asyncio.to_thread(self._claim_next_job_sync)
                if claim is None:
                    await asyncio.sleep(self._poll_interval_seconds())
                    continue
                await self._execute_claimed_job(claim)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[延后归档] worker 循环异常", exc_info=True)
                await asyncio.sleep(self._poll_interval_seconds())

    def _claim_next_job_sync(self) -> Optional[dict[str, Any]]:
        db = SessionLocal()
        try:
            now = self._database_now(db)
            job = (
                db.query(DeferredArchiveJob)
                .filter(
                    DeferredArchiveJob.cancel_requested.is_(False),
                    or_(
                        (
                            DeferredArchiveJob.status.in_(sorted(_READY_STATUSES))
                            & (DeferredArchiveJob.available_at <= func.now())
                        ),
                        (
                            (DeferredArchiveJob.status == "processing")
                            & or_(DeferredArchiveJob.lease_until.is_(None), DeferredArchiveJob.lease_until < func.now())
                        ),
                    ),
                )
                .order_by(DeferredArchiveJob.available_at.asc(), DeferredArchiveJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if job is None:
                return None
            job.status = "processing"
            job.lease_owner = self._owner
            job.lease_epoch = int(job.lease_epoch or 0) + 1
            job.lease_until = now + timedelta(seconds=_LEASE_SECONDS)
            job.updated_at = now
            db.commit()
            return {
                "job_id": job.id,
                "task_id": str(job.task_id or ""),
                "rjcode": str(job.rjcode or ""),
                "lease_epoch": int(job.lease_epoch or 0),
                "attempt_count": int(job.attempt_count or 0),
                "source_manifest": [dict(item or {}) for item in list(job.source_manifest or [])],
                "target_manifest": [dict(item or {}) for item in list(job.target_manifest or [])],
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _execute_claimed_job(self, claim: dict[str, Any]) -> None:
        job_id = str(claim["job_id"])
        epoch = int(claim["lease_epoch"])
        self._set_active_job(job_id)
        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id, epoch), name=f"deferred-archive-heartbeat:{job_id}")
        try:
            await self._update_parent_task(claim, "processing")
            self._broadcast(claim, "processing", "系统空闲，开始低优先级归档")
            for index, source in enumerate(claim["source_manifest"]):
                self._raise_if_abort(self._copy_abort_reason(job_id, epoch, check_database=True))
                await self._move_member(claim, index, source)
            completed = await asyncio.to_thread(self._complete_job_sync, job_id, epoch)
            self._remove_claims(list(completed.get("source_manifest") or []))
            await self._update_parent_task(completed, "completed")
            self._write_activity("archive_completed", "success", completed, "", None)
            self._broadcast(completed, "completed", "源压缩包已在系统空闲时归档")
        except (_YieldToForeground, _ShutdownRequested):
            released = await asyncio.to_thread(self._release_job_sync, job_id, epoch)
            if released:
                await self._update_parent_task(released, "pending")
                self._broadcast(
                    released,
                    "pending",
                    "服务关闭，归档已停止" if self._shutdown else "检测到业务任务，归档已让出资源",
                )
        except _ArchiveCancelled:
            cancelled = await asyncio.to_thread(self._cancel_job_sync, job_id, epoch)
            if cancelled:
                self._remove_claims(list(cancelled.get("source_manifest") or []))
                await self._update_parent_task(cancelled, "cancelled")
                self._write_activity("archive_cancelled", "cancelled", cancelled, "", None)
                self._broadcast(cancelled, "cancelled", "归档已取消")
        except _LeaseLost:
            # 不触碰已经由新 owner 接管的作业；它会从已发布成员状态安全恢复。
            logger.info("[延后归档] 租约已转移，停止本 worker job=%s", job_id)
        except asyncio.CancelledError:
            # 不能在这里释放租约，to_thread 可能仍在安全退出；由 stop 或超时租约恢复。
            raise
        except Exception as exc:
            failed = await asyncio.to_thread(self._fail_job_sync, job_id, epoch, str(exc))
            if failed:
                await self._update_parent_task(failed, str(failed.get("status") or "waiting_retry"))
                self._write_activity("archive_failed", "failed", failed, "", None, error=str(exc))
                self._broadcast(
                    failed,
                    str(failed.get("status") or "waiting_retry"),
                    f"归档失败，等待重试: {exc}",
                )
            logger.warning("[延后归档] job=%s 执行失败: %s", job_id, exc, exc_info=True)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat
            self._clear_active_job(job_id)

    async def _heartbeat_loop(self, job_id: str, epoch: int) -> None:
        while not self._shutdown:
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            alive = await asyncio.to_thread(self._heartbeat_sync, job_id, epoch)
            if not alive:
                self._request_active_abort(job_id, "lease_lost")
                return

    def _heartbeat_sync(self, job_id: str, epoch: int) -> bool:
        db = SessionLocal()
        try:
            now = self._database_now(db)
            updated = (
                db.query(DeferredArchiveJob)
                .filter(
                    DeferredArchiveJob.id == job_id,
                    DeferredArchiveJob.status == "processing",
                    DeferredArchiveJob.lease_owner == self._owner,
                    DeferredArchiveJob.lease_epoch == epoch,
                    DeferredArchiveJob.cancel_requested.is_(False),
                )
                .update(
                    {
                        DeferredArchiveJob.lease_until: now + timedelta(seconds=_LEASE_SECONDS),
                        DeferredArchiveJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            return bool(updated)
        except Exception:
            db.rollback()
            logger.debug("[延后归档] 心跳更新失败 job=%s", job_id, exc_info=True)
            return False
        finally:
            db.close()

    def _assert_owned(self, job: DeferredArchiveJob, epoch: int, *, allow_cancel: bool = False) -> None:
        if (
            job.status != "processing"
            or job.lease_owner != self._owner
            or int(job.lease_epoch or 0) != int(epoch)
        ):
            raise _LeaseLost("归档租约已失效")
        if bool(job.cancel_requested) and not allow_cancel:
            raise _ArchiveCancelled()

    def _control_reason_sync(self, job_id: str, epoch: int) -> str:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).first()
            if job is None:
                return "lease_lost"
            if (
                job.status != "processing"
                or job.lease_owner != self._owner
                or int(job.lease_epoch or 0) != int(epoch)
            ):
                return "lease_lost"
            if bool(job.cancel_requested):
                return "cancelled"
            return ""
        finally:
            db.close()

    def _copy_abort_reason(self, job_id: str, epoch: int, *, check_database: bool = False) -> str:
        if self._shutdown:
            return "shutdown"
        active_reason = self._active_abort_reason_for(job_id)
        if active_reason:
            return active_reason
        if self._has_foreground_work():
            return "foreground"
        if check_database:
            return self._control_reason_sync(job_id, epoch)
        return ""

    @staticmethod
    def _raise_if_abort(reason: str) -> None:
        if not reason:
            return
        if reason == "foreground":
            raise _YieldToForeground()
        if reason == "cancelled":
            raise _ArchiveCancelled()
        if reason == "lease_lost":
            raise _LeaseLost()
        raise _ShutdownRequested()

    def _owned_member_sync(self, job_id: str, epoch: int, index: int, *, allow_cancel: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().one()
            self._assert_owned(job, epoch, allow_cancel=allow_cancel)
            sources = [dict(item or {}) for item in list(job.source_manifest or [])]
            targets = [dict(item or {}) for item in list(job.target_manifest or [])]
            if index >= len(sources) or index >= len(targets):
                raise RuntimeError("归档分卷索引越界")
            return sources[index], targets[index]
        finally:
            db.close()

    async def _move_member(self, claim: dict[str, Any], index: int, source: dict[str, Any]) -> None:
        job_id = str(claim["job_id"])
        epoch = int(claim["lease_epoch"])
        async with get_resource_budget_service().acquire("disk_io_local", reason="deferred_archive.move"):
            self._set_copy_running(True)
            try:
                await asyncio.to_thread(self._move_member_sync, job_id, epoch, index, source)
            finally:
                self._set_copy_running(False)

    @staticmethod
    def _matches_source_identity(path: str, source: dict[str, Any]) -> bool:
        if not os.path.isfile(path):
            return False
        stat_result = os.stat(path)
        if int(stat_result.st_size) != int(source.get("size") or 0):
            return False
        expected_mtime = int(source.get("mtime_ns") or 0)
        actual_mtime = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
        if expected_mtime and actual_mtime != expected_mtime:
            return False
        expected_ctime = int(source.get("ctime_ns") or 0)
        actual_ctime = int(getattr(stat_result, "st_ctime_ns", int(stat_result.st_ctime * 1_000_000_000)))
        if expected_ctime and actual_ctime != expected_ctime:
            return False
        for key, attr in (("device", "st_dev"), ("inode", "st_ino")):
            expected = int(source.get(key) or 0)
            actual = int(getattr(stat_result, attr, 0) or 0)
            if expected and actual and expected != actual:
                return False
        return True

    def _hash_file(self, path: str, should_abort: Callable[[bool], str]) -> str:
        digest = hashlib.sha256()
        chunks = 0
        with open(path, "rb", buffering=0) as reader:
            while True:
                self._raise_if_abort(should_abort(chunks % _CONTROL_CHECK_CHUNKS == 0))
                chunk = reader.read(_COPY_BUFFER_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                chunks += 1
        return digest.hexdigest()

    def _copy_to_part(
        self,
        source_path: str,
        part_path: str,
        should_abort: Callable[[bool], str],
    ) -> str:
        digest = hashlib.sha256()
        chunks = 0
        try:
            with open(source_path, "rb", buffering=0) as reader, open(part_path, "xb", buffering=0) as writer:
                while True:
                    self._raise_if_abort(should_abort(chunks % _CONTROL_CHECK_CHUNKS == 0))
                    chunk = reader.read(_COPY_BUFFER_SIZE)
                    if not chunk:
                        break
                    writer.write(chunk)
                    digest.update(chunk)
                    chunks += 1
                writer.flush()
                os.fsync(writer.fileno())
            return digest.hexdigest()
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(part_path)
            raise

    @staticmethod
    def _fsync_directory(directory: str) -> None:
        """尽量把目录项落盘；Windows 的无覆盖发布已使用 WRITE_THROUGH。"""
        if os.name == "nt":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError as exc:
            unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL), getattr(errno, "EOPNOTSUPP", errno.EINVAL)}
            if exc.errno in unsupported:
                logger.debug("[延后归档] 文件系统不支持目录 fsync: %s", directory)
                return
            raise
        try:
            os.fsync(descriptor)
        except OSError as exc:
            unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL), getattr(errno, "EOPNOTSUPP", errno.EINVAL)}
            if exc.errno in unsupported:
                logger.debug("[延后归档] 文件系统不支持目录 fsync: %s", directory)
                return
            raise
        finally:
            os.close(descriptor)

    @classmethod
    def _fsync_published_target(cls, target_path: str) -> None:
        # Windows 的 MoveFileEx(..., MOVEFILE_WRITE_THROUGH) 已在发布时请求落盘；
        # Python 在只读句柄上调用 os.fsync 会稳定返回 EBADF，反而让已安全发布的
        # 目标无法进入可恢复状态。
        if os.name == "nt":
            return
        with open(target_path, "rb", buffering=0) as reader:
            os.fsync(reader.fileno())
        cls._fsync_directory(os.path.dirname(target_path))

    @staticmethod
    def _publish_part_no_replace(part_path: str, target_path: str) -> None:
        # stage 位于目标目录内。优先使用平台的 no-replace rename；硬链接只作为
        # 兼容回退，绝不使用会覆盖用户新建目标的 os.replace。
        if os.name == "nt":
            move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
            if move_file_ex(part_path, target_path, 0x00000008):  # MOVEFILE_WRITE_THROUGH
                return
            error_code = ctypes.get_last_error()
            if error_code in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
                raise FileExistsError(error_code, "归档目标在发布时已存在", target_path)
            raise OSError(error_code, "归档目标无覆盖发布失败", target_path)

        if sys.platform.startswith("linux"):
            try:
                renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
                renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                renameat2.restype = ctypes.c_int
                result = renameat2(
                    -100,
                    os.fsencode(part_path),
                    -100,
                    os.fsencode(target_path),
                    1,  # RENAME_NOREPLACE
                )
                if result == 0:
                    return
                error_code = ctypes.get_errno()
                if error_code == errno.EEXIST:
                    raise FileExistsError(error_code, "归档目标在发布时已存在", target_path)
                if error_code not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
                    raise OSError(error_code, "归档目标无覆盖发布失败", target_path)
            except AttributeError:
                pass

        try:
            os.link(part_path, target_path)
        except FileExistsError as exc:
            raise RuntimeError(f"归档目标在发布时已存在: {target_path}") from exc
        except OSError as exc:
            raise RuntimeError(f"目标文件系统不支持无覆盖归档发布: {target_path}: {exc}") from exc
        os.remove(part_path)

    def _record_member_published_sync(
        self,
        job_id: str,
        epoch: int,
        index: int,
        sha256: str,
    ) -> None:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().one()
            self._assert_owned(job, epoch)
            targets = [dict(item or {}) for item in list(job.target_manifest or [])]
            if index >= len(targets):
                raise RuntimeError("归档分卷索引越界")
            now = self._database_now(db)
            targets[index].update({
                "state": "published",
                "sha256": str(sha256 or ""),
                "published_at": now.isoformat(),
            })
            job.target_manifest = targets
            job.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _finalize_published_member_sync(
        self,
        job_id: str,
        epoch: int,
        index: int,
        checksum: str,
    ) -> None:
        """在同一行锁内验证已发布副本、删除源文件并收口成员状态。

        文件系统与数据库不能组成真正的跨资源事务。这里把唯一破坏性操作放在
        lease owner 的行锁里执行，并要求目标已持久化的 hash 可验证；即使进程在
        删除源后提交前中断，下一任 owner 也只能把这份已验证目标收口为 completed。
        """
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().one()
            self._assert_owned(job, epoch, allow_cancel=True)
            sources = [dict(item or {}) for item in list(job.source_manifest or [])]
            targets = [dict(item or {}) for item in list(job.target_manifest or [])]
            if index >= len(sources) or index >= len(targets):
                raise RuntimeError("归档分卷索引越界")
            source = sources[index]
            target = targets[index]
            source_path = str(source.get("source_path") or "")
            target_path = str(target.get("target_path") or "")
            expected_size = int(source.get("size") or 0)
            expected_checksum = str(target.get("sha256") or checksum or "")
            if not target_path or not expected_checksum:
                raise RuntimeError("归档已发布成员缺少校验信息")
            if not os.path.isfile(target_path) or os.path.getsize(target_path) != expected_size:
                raise RuntimeError(f"归档已发布目标缺失或大小错误: {target_path}")
            if self._hash_file(target_path, lambda _force: "") != expected_checksum:
                raise RuntimeError(f"归档已发布目标校验失败: {target_path}")

            if os.path.exists(source_path):
                if not self._matches_source_identity(source_path, source):
                    raise RuntimeError(f"归档源文件在发布后发生变化，拒绝删除: {source_path}")
                if self._hash_file(source_path, lambda _force: "") != expected_checksum:
                    raise RuntimeError(f"归档源文件内容与已发布目标不匹配: {source_path}")
                os.remove(source_path)
                self._fsync_directory(os.path.dirname(source_path))

            now = self._database_now(db)
            targets[index].update({
                "state": "completed",
                "sha256": expected_checksum,
                "completed_at": now.isoformat(),
            })
            job.target_manifest = targets
            job.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _move_member_sync(self, job_id: str, epoch: int, index: int, _source_hint: dict[str, Any]) -> None:
        source, target = self._owned_member_sync(job_id, epoch, index)
        source_path = str(source.get("source_path") or "")
        target_path = str(target.get("target_path") or "")
        expected_size = int(source.get("size") or 0)
        if not source_path or not target_path:
            raise RuntimeError("归档分卷缺少源路径或目标路径")
        if target.get("state") == "completed":
            if not os.path.isfile(target_path) or os.path.getsize(target_path) != expected_size:
                raise RuntimeError(f"已完成归档成员缺失或大小错误: {target_path}")
            checksum = str(target.get("sha256") or "")
            if checksum and self._hash_file(target_path, lambda _force: "") != checksum:
                raise RuntimeError(f"已完成归档成员校验失败: {target_path}")
            return

        check_counter = [0]

        def should_abort(force_database: bool = False) -> str:
            check_counter[0] += 1
            return self._copy_abort_reason(
                job_id,
                epoch,
                check_database=force_database or check_counter[0] % _CONTROL_CHECK_CHUNKS == 0,
            )

        self._raise_if_abort(should_abort(True))
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if os.path.exists(target_path):
            checksum = str(target.get("sha256") or "")
            if not checksum:
                if not self._matches_source_identity(source_path, source):
                    raise RuntimeError(f"归档目标已存在但缺少可验证发布记录: {target_path}")
                source_hash = self._hash_file(source_path, should_abort)
                target_hash = self._hash_file(target_path, should_abort)
                if source_hash != target_hash:
                    raise RuntimeError(f"归档目标已存在且内容不匹配: {target_path}")
                checksum = source_hash
                self._fsync_published_target(target_path)
                self._record_member_published_sync(job_id, epoch, index, checksum)
            else:
                if self._hash_file(target_path, should_abort) != checksum:
                    raise RuntimeError(f"归档已发布目标校验失败: {target_path}")
                self._fsync_published_target(target_path)
            self._finalize_published_member_sync(job_id, epoch, index, checksum)
            return

        if not self._matches_source_identity(source_path, source):
            raise RuntimeError(f"归档源文件已变化或不存在: {source_path}")

        checksum = ""
        published_here = False
        recorded_published = False
        try:
            # 即使源和目标在同一文件系统，也统一经由独占 .part 发布。hard link 会
            # 修改源 inode 的 ctime，既破坏冻结身份校验，也会让两个路径意外共享
            # 同一对象；低优先级归档优先保证可恢复性而非省下一次复制。
            stage_dir = os.path.join(
                os.path.dirname(target_path),
                _STAGING_DIRECTORY,
                job_id,
                f"lease-{epoch:020d}",
            )
            os.makedirs(stage_dir, exist_ok=True)
            part_path = os.path.join(stage_dir, f"{index:04d}-{os.path.basename(target_path)}.part")
            with contextlib.suppress(OSError):
                os.remove(part_path)
            checksum = self._copy_to_part(source_path, part_path, should_abort)
            if not self._matches_source_identity(source_path, source):
                raise RuntimeError(f"归档复制期间源文件已变化: {source_path}")
            if self._hash_file(source_path, should_abort) != checksum:
                raise RuntimeError(f"归档复制后的源文件校验失败: {source_path}")
            self._publish_part_no_replace(part_path, target_path)
            published_here = True
            if os.path.getsize(target_path) != expected_size:
                raise RuntimeError(f"归档目标大小校验失败: {target_path}")
            if not checksum:
                checksum = self._hash_file(target_path, should_abort)
            if not self._matches_source_identity(source_path, source):
                raise RuntimeError(f"归档发布前源文件已变化: {source_path}")
            if self._hash_file(source_path, should_abort) != checksum:
                raise RuntimeError(f"归档发布前源文件校验失败: {source_path}")
            if self._hash_file(target_path, should_abort) != checksum:
                raise RuntimeError(f"归档目标内容校验失败: {target_path}")
            self._fsync_published_target(target_path)
            # 先持久化发布状态，崩溃后可凭 checksum 恢复，之后才允许删除源文件。
            self._record_member_published_sync(job_id, epoch, index, checksum)
            recorded_published = True
            self._finalize_published_member_sync(job_id, epoch, index, checksum)
        except (_YieldToForeground, _ArchiveCancelled, _ShutdownRequested):
            if published_here and not recorded_published:
                # 还没有写 published 状态时目标完全由本次调用创建，可以安全回滚目标。
                with contextlib.suppress(OSError):
                    os.remove(target_path)
            raise

    def _complete_job_sync(self, job_id: str, epoch: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().one()
            self._assert_owned(job, epoch, allow_cancel=True)
            sources = [dict(item or {}) for item in list(job.source_manifest or [])]
            targets = [dict(item or {}) for item in list(job.target_manifest or [])]
            if not sources or len(sources) != len(targets):
                raise RuntimeError("归档分卷清单不完整")
            for source, target in zip(sources, targets):
                path = str(target.get("target_path") or "")
                if (
                    target.get("state") != "completed"
                    or not os.path.isfile(path)
                    or os.path.getsize(path) != int(source.get("size") or 0)
                ):
                    raise RuntimeError(f"归档目标校验失败: {path}")
                if os.path.exists(str(source.get("source_path") or "")):
                    raise RuntimeError(f"归档源文件仍存在，拒绝完成: {source.get('source_path')}")
            main_source = sources[0]
            main_target = targets[0]
            current_path = str(main_target.get("target_path") or "")
            filename = os.path.basename(current_path)
            existing = db.query(ProcessedArchive).filter(ProcessedArchive.current_path == current_path).first()
            total_size = sum(int(item.get("size") or 0) for item in sources)
            now = self._database_now(db)
            if existing is None:
                existing = ProcessedArchive(
                    id=str(uuid.uuid4()),
                    original_path=str(main_source.get("source_path") or ""),
                    current_path=current_path,
                    filename=filename,
                    rjcode=str(job.rjcode or ""),
                    file_size=total_size,
                    volume_count=len(sources),
                    archive_manifest=targets,
                    processed_at=now,
                    process_count=1,
                    task_id=job.task_id,
                    status="completed",
                )
                db.add(existing)
            else:
                existing.original_path = str(main_source.get("source_path") or "")
                existing.filename = filename
                existing.rjcode = str(job.rjcode or existing.rjcode or "")
                existing.file_size = total_size
                existing.volume_count = len(sources)
                existing.archive_manifest = targets
                existing.processed_at = now
                existing.process_count = int(existing.process_count or 0) + 1
                existing.task_id = job.task_id
                existing.status = "completed"
            job.status = "completed"
            job.completed_at = now
            job.updated_at = now
            job.lease_owner = None
            job.lease_until = None
            job.cancel_requested = False
            job.last_error = None
            db.commit()
            try:
                from .task_center_event_service import broadcast_processed_archive_changed

                broadcast_processed_archive_changed(existing)
            except Exception:
                logger.debug("[延后归档] 广播归档完成失败", exc_info=True)
            self._cleanup_empty_source_dirs(sources)
            self._cleanup_staging_dir(targets)
            return self._job_payload(job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _release_job_sync(self, job_id: str, epoch: int) -> Optional[dict[str, Any]]:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().first()
            if job is None:
                return None
            self._assert_owned(job, epoch)
            job.status = "pending"
            now = self._database_now(db)
            job.available_at = now
            job.lease_owner = None
            job.lease_until = None
            job.updated_at = now
            db.commit()
            return self._job_payload(job)
        except _ArchiveCancelled:
            db.rollback()
            return self._cancel_job_sync(job_id, epoch)
        except _LeaseLost:
            db.rollback()
            return None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _cancel_job_sync(self, job_id: str, epoch: int) -> Optional[dict[str, Any]]:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().first()
            if job is None or int(job.lease_epoch or 0) != epoch or job.lease_owner != self._owner:
                return None
            # 一旦有任何成员发布，取消无法原子恢复整组，保留作业由下一次空闲完成。
            if any(str((item or {}).get("state") or "") != "pending" for item in list(job.target_manifest or [])):
                job.cancel_requested = False
                job.status = "pending"
                now = self._database_now(db)
                job.available_at = now
                job.lease_owner = None
                job.lease_until = None
                job.updated_at = now
                db.commit()
                return self._job_payload(job)
            job.status = "cancelled"
            now = self._database_now(db)
            job.completed_at = now
            job.updated_at = now
            job.lease_owner = None
            job.lease_until = None
            db.commit()
            return self._job_payload(job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _fail_job_sync(self, job_id: str, epoch: int, error: str) -> Optional[dict[str, Any]]:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(DeferredArchiveJob.id == job_id).with_for_update().first()
            if job is None:
                return None
            if int(job.lease_epoch or 0) != epoch or job.lease_owner != self._owner:
                return None
            attempt = int(job.attempt_count or 0) + 1
            job.attempt_count = attempt
            job.last_error = str(error or "归档失败")[:4000]
            job.lease_owner = None
            job.lease_until = None
            now = self._database_now(db)
            job.updated_at = now
            if attempt >= self._max_retry_count():
                job.status = "failed"
                job.completed_at = now
            else:
                job.status = "waiting_retry"
                delay = min(self._retry_delay_seconds() * attempt, 24 * 3600)
                job.available_at = now + timedelta(seconds=delay)
            db.commit()
            return self._job_payload(job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _release_owned_jobs_sync(self) -> None:
        db = SessionLocal()
        try:
            now = self._database_now(db)
            db.query(DeferredArchiveJob).filter(
                DeferredArchiveJob.status == "processing",
                DeferredArchiveJob.lease_owner == self._owner,
            ).update(
                {
                    DeferredArchiveJob.status: "pending",
                    DeferredArchiveJob.available_at: now,
                    DeferredArchiveJob.lease_owner: None,
                    DeferredArchiveJob.lease_until: None,
                    DeferredArchiveJob.updated_at: now,
                },
                synchronize_session=False,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.debug("[延后归档] 释放本机租约失败", exc_info=True)
        finally:
            db.close()

    def request_cancel_sync(self, job_id: str) -> bool:
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(
                DeferredArchiveJob.id == str(job_id or "")
            ).with_for_update().first()
            if job is None or job.status in {"completed", "cancelled"}:
                return False
            # 已发布任何成员时取消会留下一个拆开的分卷组，拒绝而不是制造不可恢复状态。
            if any(str((item or {}).get("state") or "") != "pending" for item in list(job.target_manifest or [])):
                return False
            job.cancel_requested = True
            now = self._database_now(db)
            if job.status != "processing":
                job.status = "cancelled"
                job.completed_at = now
            job.updated_at = now
            db.commit()
            self._request_active_abort(str(job.id or ""), "cancelled")
            if job.status == "cancelled":
                self._remove_claims(list(job.source_manifest or []))
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def retry_failed_sync(self, job_id: str) -> bool:
        """人工恢复失败归档作业，已发布成员会由恢复 worker 校验后继续收口。"""
        db = SessionLocal()
        try:
            job = db.query(DeferredArchiveJob).filter(
                DeferredArchiveJob.id == str(job_id or "")
            ).with_for_update().first()
            if job is None or str(job.status or "") != "failed":
                return False
            now = self._database_now(db)
            job.status = "pending"
            job.available_at = now
            job.attempt_count = 0
            job.last_error = None
            job.completed_at = None
            job.cancel_requested = False
            job.lease_owner = None
            job.lease_until = None
            job.updated_at = now
            db.commit()
            self._add_claims(list(job.source_manifest or []))
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job_payload(job: Any) -> dict[str, Any]:
        return {
            "job_id": str(getattr(job, "id", "") or ""),
            "task_id": str(getattr(job, "task_id", "") or ""),
            "rjcode": str(getattr(job, "rjcode", "") or ""),
            "status": str(getattr(job, "status", "") or ""),
            "attempt_count": int(getattr(job, "attempt_count", 0) or 0),
            "last_error": str(getattr(job, "last_error", "") or ""),
            "source_manifest": [dict(item or {}) for item in list(getattr(job, "source_manifest", None) or [])],
            "target_manifest": [dict(item or {}) for item in list(getattr(job, "target_manifest", None) or [])],
        }

    def _cleanup_empty_source_dirs(self, manifest: list[dict[str, Any]]) -> None:
        config = get_config()
        protected = {
            _normalized_path(path)
            for path in (
                getattr(config.storage, "input_path", ""),
                getattr(config.storage, "processed_archives_path", ""),
                getattr(config.storage, "temp_path", ""),
                getattr(config.storage, "library_path", ""),
                getattr(config.storage, "existing_folders_path", ""),
            )
            if path
        }
        for item in manifest:
            current = os.path.dirname(str(item.get("source_path") or ""))
            while current:
                normalized = _normalized_path(current)
                parent = os.path.dirname(current)
                if not os.path.isdir(current) or normalized in protected or parent == current:
                    break
                try:
                    if os.listdir(current):
                        break
                    os.rmdir(current)
                except OSError:
                    break
                current = parent

    def _cleanup_staging_dir(self, manifest: list[dict[str, Any]]) -> None:
        """完成归档后仅清理空 staging 目录，不触碰其他 lease 的恢复文件。"""
        staging_roots = {
            os.path.join(os.path.dirname(str(item.get("target_path") or "")), _STAGING_DIRECTORY)
            for item in manifest
            if str(item.get("target_path") or "").strip()
        }
        for staging_root in staging_roots:
            if not staging_root or not os.path.isdir(staging_root):
                continue
            for root, directories, files in os.walk(staging_root, topdown=False):
                with contextlib.suppress(OSError):
                    os.rmdir(root)

    async def _update_parent_task(self, payload: dict[str, Any], status: str) -> None:
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            return
        try:
            from .task_engine import get_task_engine

            task = get_task_engine().get_task(task_id)
            if task is None:
                return
            metadata = dict(task.task_metadata or {})
            metadata.update({
                "archive_queue_id": str(payload.get("job_id") or metadata.get("archive_queue_id") or ""),
                "archive_queue_status": status,
                "archive_attempt_count": int(payload.get("attempt_count") or 0),
                "archive_last_error": str(payload.get("last_error") or ""),
            })
            task.task_metadata = metadata
            labels = {
                "pending": "入库完成，源压缩包等待系统空闲归档",
                "processing": "入库完成，正在低优先级归档源压缩包",
                "waiting_retry": "入库完成，源压缩包归档等待重试",
                "completed": "入库完成，源压缩包已归档",
                "failed": "入库完成，但源压缩包归档失败",
                "cancelled": "入库完成，源压缩包归档已取消",
            }
            task.current_step = labels.get(status, task.current_step)
            touch = getattr(task, "touch_metadata", None)
            if callable(touch):
                touch("archive_queue")
        except Exception:
            logger.debug("[延后归档] 更新父任务展示失败", exc_info=True)

    def _broadcast(self, payload: dict[str, Any], status: str, step: str) -> None:
        try:
            from .realtime_event_service import broadcast_event

            broadcast_event({
                "type": "archive.queue.changed",
                "reason": "deferred_archive",
                "id": str(payload.get("job_id") or ""),
                "domain": "archive",
                "status": status,
                "current_step": step,
                "payload": {**dict(payload or {}), "status": status, "current_step": step},
            })
        except Exception:
            logger.debug("[延后归档] 实时事件广播失败", exc_info=True)

    def _write_activity(
        self,
        action: str,
        status: str,
        payload: dict[str, Any],
        source_path: str,
        task: Any,
        *,
        error: str = "",
    ) -> None:
        try:
            from .activity_log_service import write_activity_log

            details = {
                "archive_job_id": str(payload.get("job_id") or ""),
                "archive_status": str(payload.get("status") or status),
                "attempt_count": int(payload.get("attempt_count") or 0),
                "volume_count": len(payload.get("source_manifest") or []),
                "error": error or str(payload.get("last_error") or ""),
            }
            write_activity_log(
                "auto_import",
                action,
                status,
                "源压缩包已加入空闲归档队列" if action == "archive_queued" else "源压缩包空闲归档完成" if action == "archive_completed" else "源压缩包空闲归档异常",
                detail=details,
                rjcode=str(payload.get("rjcode") or getattr(task, "rjcode", "") or ""),
                task_id=str(payload.get("task_id") or getattr(task, "id", "") or ""),
                source_path=source_path or str(getattr(task, "source_path", "") or ""),
            )
        except Exception:
            logger.debug("[延后归档] 写操作历史失败", exc_info=True)


_deferred_archive_service: Optional[DeferredArchiveService] = None


def get_deferred_archive_service() -> DeferredArchiveService:
    global _deferred_archive_service
    if _deferred_archive_service is None:
        _deferred_archive_service = DeferredArchiveService()
    return _deferred_archive_service
