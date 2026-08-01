"""库存索引 mutation 账本、可见性遮罩和 PostgreSQL 驱动的顺序物化。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import queue
import socket
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import and_, case, exists, func, or_, text
from sqlalchemy.orm import Session

from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexGeneration,
    LibraryIndexMutationEffect,
    LibraryIndexMutationLedger,
    LibraryIndexMutationOperation,
    LibraryIndexPendingMask,
    LibraryIndexStatus,
    SessionLocal,
    engine as main_engine,
    get_local_now,
)
from ..redis_service import get_redis_service
from ..resource_budget_service import get_resource_budget_service
from .local_scanner import LocalScanner
from .materializer_db import (
    dispose_materializer_engine,
    get_materializer_session_factory,
    materializer_pool_diagnostics,
)
from .snapshot_store import (
    DEFAULT_BULK_UPSERT_CHUNK_SIZE,
    SnapshotStore,
    get_snapshot_store,
)
from .types import IndexEntry

logger = logging.getLogger(__name__)
_DEFAULT_SESSION_FACTORY = SessionLocal

LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 10
SWEEP_SECONDS = 0.25
MAX_ATTEMPTS = 10
RETRY_DELAYS_SECONDS = (1, 2, 5, 10, 30, 60)
RECOVERY_BATCH_SIZE = 100
PREPARED_RECOVERY_STALE_SECONDS = 300
RECOVERY_SWEEP_SECONDS = 30.0
LEDGER_RETENTION_DAYS = 7
LEDGER_CLEANUP_SWEEP_SECONDS = 3600.0
LEDGER_CLEANUP_CHUNK_SIZE = 500
FAST_PATH_MAX_EFFECTS = 50
FAST_PATH_MAX_ROWS = 5000
FAST_PATH_LOCK_TIMEOUT_MS = 200
FAST_PATH_STATEMENT_TIMEOUT_MS = 1500
FAST_PATH_PAUSE_SECONDS = 1.0
TARGETED_RECONCILE_MAX_ROWS = 5000


class _FastPathLimitExceeded(RuntimeError):
    """精确事务超过 effects/行数预算，交回原有慢通道。"""


class _FastPathRetryLater(RuntimeError):
    """锁或语句超时，回滚后等待 safety sweep 重试。"""


def _normalize_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    parts: list[str] = []
    for part in text.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("库存索引相对路径不能包含 ..")
        parts.append(part)
    return "/".join(parts)


def _normalize_effect(raw: dict[str, Any]) -> dict[str, Any]:
    effect = dict(raw or {})
    kind = str(effect.get("kind") or "reconcile").strip().lower()
    if kind not in {
        "delete",
        "replace",
        "move",
        "move_target",
        "reconcile",
        "upsert",
    }:
        raise ValueError(f"不支持的库存索引 effect: {kind}")
    scope = str(effect.get("scope") or "exact").strip().lower()
    if scope not in {"exact", "subtree"}:
        raise ValueError(f"不支持的库存索引 scope: {scope}")
    return {
        "kind": kind,
        "relative_path": _normalize_relative_path(effect.get("relative_path")),
        "scope": scope,
        "target_library_id": str(effect.get("target_library_id") or "").strip() or None,
        "target_path": (
            _normalize_relative_path(effect.get("target_path"))
            if effect.get("target_path") is not None
            else None
        ),
        "payload": dict(effect.get("payload") or {}),
    }


def _request_fingerprint(kind: str, scopes: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {"kind": kind, "scopes": scopes},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(slots=True)
class PreparedMutation:
    operation_id: str
    idempotency_key: str
    state: str
    replayed: bool = False
    result: Optional[dict[str, Any]] = None


class LibraryIndexMutationService:
    def __init__(
        self,
        *,
        materializer_session_factory=None,
        fast_path_enabled: Optional[bool] = None,
    ) -> None:
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._recovery_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lifecycle_lock = threading.Lock()
        self._consumer_name = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._reclaim_cursor = "0-0"
        self._replay_count = 0
        self._prepared_scopes_lock = threading.Lock()
        self._prepared_scopes: dict[str, list[dict[str, Any]]] = {}
        self._materializer_session_factory = materializer_session_factory
        self._fast_path_enabled = (
            bool(fast_path_enabled)
            if fast_path_enabled is not None
            else str(os.getenv("KIKOERUMANAGER_LIBRARY_INDEX_FAST_PATH", "0")).lower()
            in {"1", "true", "yes", "on"}
        )
        self._publisher_queue: queue.Queue[tuple[str, int, str]] = queue.Queue()
        self._publisher_thread: Optional[threading.Thread] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._listener_hints_queue: queue.Queue[
            list[tuple[str, dict[str, Any]]]
        ] = queue.Queue()
        self._last_fast_path_pause_until = 0.0
        self._fast_path_last_duration_ms = 0.0
        self._fast_path_timeout_count = 0
        self._fast_path_last_fallback_reason: Optional[str] = None

    def _materializer_session(self):
        factory = self._materializer_session_factory
        if factory is None:
            # 测试会替换模块级 SessionLocal；此时必须继续使用测试事务，不能连接真实专用池。
            factory = (
                SessionLocal
                if SessionLocal is not _DEFAULT_SESSION_FACTORY
                else get_materializer_session_factory()
            )
        return factory()

    def _materializer_store(self) -> SnapshotStore:
        factory = self._materializer_session_factory
        if factory is None and SessionLocal is not _DEFAULT_SESSION_FACTORY:
            return get_snapshot_store()
        if factory is None:
            factory = get_materializer_session_factory()
        return SnapshotStore(session_factory=factory)

    @staticmethod
    def _main_pool_under_pressure() -> bool:
        try:
            pool = main_engine.pool
            pool_size = max(1, int(pool.size()))
            checked_out = int(pool.checkedout())
            threshold = max(1, int(pool_size * 0.7))
            return checked_out >= threshold or pool_size - min(checked_out, pool_size) < min(3, pool_size)
        except Exception:
            return False

    def _should_pause_fast_path(self) -> bool:
        if time.monotonic() < self._last_fast_path_pause_until:
            return True
        try:
            snapshot = get_resource_budget_service().snapshot()
            database_write = (snapshot.get("resources") or {}).get("database_write") or {}
            if int(database_write.get("waiting") or 0) > 0:
                return True
        except Exception:
            pass
        if self._main_pool_under_pressure():
            return True
        if self._fast_path_last_duration_ms > 500:
            self._last_fast_path_pause_until = time.monotonic() + SWEEP_SECONDS
            self._fast_path_last_duration_ms = 0.0
            return True
        return False

    def _materializer_pool_diagnostics(self) -> dict[str, int]:
        try:
            return materializer_pool_diagnostics()
        except Exception:
            return {"pool_size": 1, "checked_out": 0, "overflow": 0}

    @staticmethod
    def _ensure_status(db, library_id: str, *, for_update: bool = False) -> LibraryIndexStatus:
        query = db.query(LibraryIndexStatus).filter(LibraryIndexStatus.library_id == library_id)
        if for_update:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            row = LibraryIndexStatus(
                library_id=library_id,
                status="idle",
                watcher_mode="disabled",
                accepted_seq=0,
                materialized_seq=0,
                state_revision=0,
                view_revision=0,
                active_generation=1,
                materializer_epoch=0,
                catchup_state="idle",
                updated_at=int(time.time() * 1000),
            )
            db.add(row)
            db.flush()
            if for_update:
                row = query.with_for_update().one()
        return row

    def prepare(
        self,
        *,
        kind: str,
        effects_by_library: dict[str, Iterable[dict[str, Any]]],
        idempotency_key: str,
        operation_id: Optional[str] = None,
    ) -> PreparedMutation:
        normalized_kind = str(kind or "mutation").strip().lower()
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            raise ValueError("确认型库存操作必须提供 Idempotency-Key")
        scopes: list[dict[str, Any]] = []
        for library_id in sorted(effects_by_library):
            lid = str(library_id or "").strip()
            if not lid:
                continue
            for effect_no, raw in enumerate(effects_by_library[library_id]):
                effect = _normalize_effect(raw)
                scopes.append({"library_id": lid, "effect_no": effect_no, **effect})
        if not scopes:
            raise ValueError("库存索引 mutation 没有有效 effect")
        fingerprint = _request_fingerprint(normalized_kind, scopes)
        db = SessionLocal()
        try:
            existing = (
                db.query(LibraryIndexMutationOperation)
                .filter(LibraryIndexMutationOperation.idempotency_key == normalized_key)
                .first()
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ValueError("同一个 Idempotency-Key 不能用于不同请求")
                return PreparedMutation(
                    operation_id=existing.operation_id,
                    idempotency_key=normalized_key,
                    state=existing.state,
                    replayed=True,
                    result=dict(existing.actual_result or {}),
                )

            resolved_operation_id = str(operation_id or uuid.uuid4())
            operation = LibraryIndexMutationOperation(
                operation_id=resolved_operation_id,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
                kind=normalized_kind,
                state="prepared",
                planned_scopes=scopes,
                actual_result={},
            )
            db.add(operation)
            for scope in scopes:
                db.add(LibraryIndexPendingMask(
                    operation_id=resolved_operation_id,
                    library_id=scope["library_id"],
                    ledger_seq=None,
                    effect_no=int(scope["effect_no"]),
                    kind=scope["kind"],
                    relative_path=scope["relative_path"],
                    scope=scope["scope"],
                ))
            for library_id in sorted({scope["library_id"] for scope in scopes}):
                status = self._ensure_status(db, library_id, for_update=True)
                status.view_revision = int(status.view_revision or 0) + 1
                status.state_revision = int(status.state_revision or 0) + 1
                status.catchup_state = "prepared"
                status.updated_at = int(time.time() * 1000)
            db.commit()
            with self._prepared_scopes_lock:
                self._prepared_scopes[resolved_operation_id] = [dict(scope) for scope in scopes]
            self._broadcast_libraries({scope["library_id"] for scope in scopes}, "mutation_prepared")
            return PreparedMutation(
                operation_id=resolved_operation_id,
                idempotency_key=normalized_key,
                state="prepared",
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def fail_prepared(self, operation_id: str, error: Any) -> dict[str, Any]:
        db = SessionLocal()
        library_ids: set[str] = set()
        try:
            operation = (
                db.query(LibraryIndexMutationOperation)
                .filter(LibraryIndexMutationOperation.operation_id == operation_id)
                .with_for_update()
                .one()
            )
            if operation.state == "committed":
                with self._prepared_scopes_lock:
                    self._prepared_scopes.pop(operation_id, None)
                return operation.to_dict()
            masks = (
                db.query(LibraryIndexPendingMask)
                .filter(LibraryIndexPendingMask.operation_id == operation_id)
                .all()
            )
            library_ids = {mask.library_id for mask in masks}
            db.query(LibraryIndexPendingMask).filter(
                LibraryIndexPendingMask.operation_id == operation_id
            ).delete(synchronize_session=False)
            operation.state = "failed"
            operation.error = str(error or "文件系统操作失败")
            operation.finalized_at = get_local_now()
            for library_id in sorted(library_ids):
                status = self._ensure_status(db, library_id, for_update=True)
                status.view_revision = int(status.view_revision or 0) + 1
                status.state_revision = int(status.state_revision or 0) + 1
                status.catchup_state = (
                    "catching_up"
                    if int(status.accepted_seq or 0) > int(status.materialized_seq or 0)
                    else "idle"
                )
                status.updated_at = int(time.time() * 1000)
            db.commit()
            result = operation.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        with self._prepared_scopes_lock:
            self._prepared_scopes.pop(operation_id, None)
        self._broadcast_libraries(library_ids, "mutation_rolled_back")
        return result

    def mark_filesystem_started(self, operation_id: str) -> dict[str, Any]:
        """在触碰文件系统前持久化崩溃恢复边界。"""
        db = SessionLocal()
        try:
            operation = (
                db.query(LibraryIndexMutationOperation)
                .filter(LibraryIndexMutationOperation.operation_id == operation_id)
                .with_for_update()
                .one()
            )
            if operation.state != "prepared":
                return operation.to_dict()
            if operation.filesystem_started_at is None:
                operation.filesystem_started_at = get_local_now()
                operation.updated_at = get_local_now()
                db.commit()
            return operation.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_reconcile_required(self, operation_id: str, error: Any) -> dict[str, Any]:
        db = SessionLocal()
        library_ids: set[str] = set()
        try:
            operation = (
                db.query(LibraryIndexMutationOperation)
                .filter(LibraryIndexMutationOperation.operation_id == operation_id)
                .with_for_update()
                .one()
            )
            if operation.state == "committed":
                result = dict(operation.actual_result or operation.to_dict())
                db.rollback()
                with self._prepared_scopes_lock:
                    self._prepared_scopes.pop(operation_id, None)
                return result
            library_ids = {
                str(scope.get("library_id") or "").strip()
                for scope in (operation.planned_scopes or [])
                if str(scope.get("library_id") or "").strip()
            }
            operation.state = "reconcile_required"
            operation.error = str(error or "ledger finalize failed")
            operation.updated_at = get_local_now()
            for library_id in sorted(library_ids):
                status = self._ensure_status(db, library_id, for_update=True)
                status.state_revision = int(status.state_revision or 0) + 1
                status.catchup_state = "reconcile_required"
                status.catchup_error = operation.error
                status.updated_at = int(time.time() * 1000)
            db.commit()
            result = operation.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        with self._prepared_scopes_lock:
            self._prepared_scopes.pop(operation_id, None)
        self._recovery_event.set()
        self._wake_event.set()
        self._broadcast_libraries(library_ids, "mutation_reconcile_required")
        return result

    def finalize(
        self,
        operation_id: str,
        *,
        actual_effects_by_library: dict[str, Iterable[dict[str, Any]]],
        actual_result: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        normalized: dict[str, list[dict[str, Any]]] = {}
        for library_id in sorted(actual_effects_by_library):
            lid = str(library_id or "").strip()
            effects = [_normalize_effect(raw) for raw in actual_effects_by_library[library_id]]
            if lid and effects:
                normalized[lid] = effects
        db = SessionLocal()
        fences: list[dict[str, Any]] = []
        hints: list[tuple[str, int]] = []
        try:
            operation = (
                db.query(LibraryIndexMutationOperation)
                .filter(LibraryIndexMutationOperation.operation_id == operation_id)
                .with_for_update()
                .one()
            )
            if operation.state == "committed":
                with self._prepared_scopes_lock:
                    self._prepared_scopes.pop(operation_id, None)
                return dict(operation.actual_result or {})
            planned_library_ids = sorted({
                str(scope.get("library_id") or "")
                for scope in (operation.planned_scopes or [])
                if scope.get("library_id")
            } | set(normalized))
            for library_id in planned_library_ids:
                self._ensure_status(db, library_id, for_update=True)

            for library_id, effects in normalized.items():
                status = self._ensure_status(db, library_id, for_update=True)
                seq = int(status.accepted_seq or 0) + 1
                ledger = LibraryIndexMutationLedger(
                    operation_id=operation_id,
                    library_id=library_id,
                    seq=seq,
                    kind=operation.kind,
                    payload={"effect_count": len(effects)},
                )
                db.add(ledger)
                db.flush()
                for effect_no, effect in enumerate(effects):
                    db.add(LibraryIndexMutationEffect(
                        ledger_id=ledger.id,
                        operation_id=operation_id,
                        library_id=library_id,
                        seq=seq,
                        effect_no=effect_no,
                        kind=effect["kind"],
                        relative_path=effect["relative_path"],
                        scope=effect["scope"],
                        target_library_id=effect["target_library_id"],
                        target_path=effect["target_path"],
                        payload=effect["payload"],
                    ))
                status.accepted_seq = seq
                status.state_revision = int(status.state_revision or 0) + 1
                status.view_revision = int(status.view_revision or 0) + 1
                status.catchup_state = "catching_up"
                status.last_operation_id = operation_id
                status.updated_at = int(time.time() * 1000)
                hints.append((library_id, seq))
                fences.append(self._fence(status, operation_id, seq, effects))

            db.query(LibraryIndexPendingMask).filter(
                LibraryIndexPendingMask.operation_id == operation_id
            ).delete(synchronize_session=False)
            for library_id, effects in normalized.items():
                seq = next(seq for lid, seq in hints if lid == library_id)
                for effect_no, effect in enumerate(effects):
                    db.add(LibraryIndexPendingMask(
                        operation_id=operation_id,
                        library_id=library_id,
                        ledger_seq=seq,
                        effect_no=effect_no,
                        kind=effect["kind"],
                        relative_path=effect["relative_path"],
                        scope=effect["scope"],
                    ))
            for library_id in planned_library_ids:
                if library_id in normalized:
                    continue
                status = self._ensure_status(db, library_id, for_update=True)
                status.view_revision = int(status.view_revision or 0) + 1
                status.state_revision = int(status.state_revision or 0) + 1
                status.catchup_state = (
                    "catching_up"
                    if int(status.accepted_seq or 0) > int(status.materialized_seq or 0)
                    else "idle"
                )
                status.updated_at = int(time.time() * 1000)

            response = {
                **dict(actual_result or {}),
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": fences,
            }
            operation.state = "committed"
            operation.actual_result = response
            operation.error = None
            operation.finalized_at = get_local_now()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        self._broadcast_libraries(set(planned_library_ids), "mutation_committed")
        with self._prepared_scopes_lock:
            self._prepared_scopes.pop(operation_id, None)
        redis = get_redis_service()
        for library_id, seq in hints:
            self._enqueue_mutation_hint(redis, library_id, seq, operation_id)
        self._wake_event.set()
        return response

    def _enqueue_mutation_hint(self, redis, library_id: str, seq: int, operation_id: str) -> None:
        """提交后唤醒与 Redis 发布解耦；未启动后台线程时保留同步兼容行为。"""
        if self._publisher_thread is None or not self._publisher_thread.is_alive():
            try:
                redis.publish_library_index_mutation_hint_sync(library_id, seq, operation_id)
            except Exception:
                logger.warning(
                    "[索引追赶] Redis wake hint 发布失败，等待 PostgreSQL sweeper 补偿 "
                    "library=%s seq=%s operation=%s",
                    library_id,
                    seq,
                    operation_id,
                    exc_info=True,
                )
            return
        self._publisher_queue.put((str(library_id), int(seq), str(operation_id)))

    def _publisher_run(self) -> None:
        while not self._stop_event.is_set() or not self._publisher_queue.empty():
            try:
                library_id, seq, operation_id = self._publisher_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                get_redis_service().publish_library_index_mutation_hint_sync(
                    library_id,
                    seq,
                    operation_id,
                )
            except Exception:
                logger.warning(
                    "[索引追赶] Redis wake hint 异步发布失败，等待 PostgreSQL safety sweep "
                    "library=%s seq=%s operation=%s",
                    library_id,
                    seq,
                    operation_id,
                    exc_info=True,
                )
            finally:
                self._publisher_queue.task_done()

    def _listener_run(self) -> None:
        """阻塞读取 Redis Stream，仅投递内存提示并唤醒 PostgreSQL 物化器。"""
        while not self._stop_event.is_set():
            try:
                redis = get_redis_service()
                self._reclaim_cursor, hints = (
                    redis.read_library_index_mutation_hints_sync(
                        self._consumer_name,
                        count=100,
                        block_ms=250,
                        reclaim_idle_ms=60000,
                        reclaim_cursor=self._reclaim_cursor,
                    )
                )
                if hints:
                    self._listener_hints_queue.put(hints)
                    self._wake_event.set()
            except Exception:
                logger.debug("[索引追赶] Redis hint listener 读取失败", exc_info=True)
                self._stop_event.wait(SWEEP_SECONDS)

    def _ack_listener_hints(self) -> None:
        batches: list[list[tuple[str, dict[str, Any]]]] = []
        while True:
            try:
                batches.append(self._listener_hints_queue.get_nowait())
            except queue.Empty:
                break
        if not batches:
            return
        hints = [hint for batch in batches for hint in batch]
        try:
            redis = get_redis_service()
            watermarks, retry_seqs = self._hint_ack_state(hints)
            result = redis.ack_durable_library_index_mutation_hints_sync(
                hints,
                materialized_seq_by_library=watermarks,
                retry_persisted_seqs=retry_seqs,
            )
            deferred = set(result.get("deferred_message_ids") or [])
            if deferred:
                retry_hints = [
                    hint for hint in hints if str(hint[0]) in deferred
                ]
                if retry_hints:
                    self._listener_hints_queue.put(retry_hints)
        except Exception:
            self._listener_hints_queue.put(hints)
            logger.debug("[索引追赶] Redis hint ACK 判定失败", exc_info=True)
        finally:
            for batch in batches:
                self._listener_hints_queue.task_done()

    @staticmethod
    def _fence(status, operation_id: str, seq: int, effects: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "operation_id": operation_id,
            "library_id": status.library_id,
            "accepted_seq": int(seq),
            "state_revision": int(status.state_revision or 0),
            "view_revision": int(status.view_revision or 0),
            "active_generation": int(status.active_generation or 1),
            "effects": [
                {
                    "seq": int(seq),
                    "kind": (
                        "reconcile"
                        if effect["kind"] == "move_target"
                        else effect["kind"]
                    ),
                    "relative_path": effect["relative_path"],
                    "scope": effect["scope"],
                }
                for effect in effects
            ],
        }

    def get_operation_by_idempotency_key(self, idempotency_key: str) -> Optional[dict[str, Any]]:
        db = SessionLocal()
        try:
            row = db.query(LibraryIndexMutationOperation).filter(
                LibraryIndexMutationOperation.idempotency_key == str(idempotency_key or "")
            ).first()
            return row.to_dict() if row else None
        finally:
            db.close()

    @staticmethod
    def _path_filter(column, relative_path: str, scope: str):
        if scope == "subtree":
            if not relative_path:
                return column.is_not(None)
            return or_(
                column == relative_path,
                (column >= f"{relative_path}/") & (column < f"{relative_path}0"),
            )
        return column == relative_path

    def should_suppress_watcher(self, library_id: str, relative_path: str) -> bool:
        """watchdog 回调可安全调用；只读进程内 prepared scope，不做数据库 IO。"""
        normalized = _normalize_relative_path(relative_path)
        with self._prepared_scopes_lock:
            scopes = [scope for values in self._prepared_scopes.values() for scope in values]
        for scope in scopes:
            if str(scope.get("library_id") or "") != str(library_id or ""):
                continue
            root = str(scope.get("relative_path") or "")
            if normalized == root:
                return True
            if str(scope.get("scope") or "exact") == "subtree" and (
                not root or normalized.startswith(root + "/")
            ):
                return True
        return False

    @staticmethod
    def _fast_path_timeout(exc: Exception) -> bool:
        message = str(exc or "").lower()
        return any(
            marker in message
            for marker in (
                "lock timeout",
                "statement timeout",
                "canceling statement",
                "deadlock detected",
                "connection timed out",
            )
        )

    def _entry_snapshot_for_exact_effect(
        self,
        library_id: str,
        effect: LibraryIndexMutationEffect,
        *,
        generation: int,
        materialized_seq: int,
    ) -> Optional[IndexEntry]:
        payload = dict(effect.payload or {})
        snapshot = payload.get("entry_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = payload if payload.get("entry_type") else None
        if snapshot is None:
            from ..library_manager import get_library_manager

            library = get_library_manager().get_library_definition(library_id)
            if library.type != "local":
                return None
            root = os.path.abspath(library.root_path or "")
            target = os.path.abspath(
                os.path.join(root, *str(effect.relative_path or "").split("/"))
            )
            try:
                if os.path.commonpath([root, target]).casefold() != root.casefold():
                    return None
                stat_result = os.stat(target)
            except (OSError, ValueError):
                return None
            entry_type = "dir" if os.path.isdir(target) else "file"
            snapshot = {
                "entry_type": entry_type,
                "relative_path": effect.relative_path,
                "absolute_path": target,
                "name": os.path.basename(target) or os.path.basename(root),
                "parent_path": (
                    str(effect.relative_path or "").rsplit("/", 1)[0]
                    if "/" in str(effect.relative_path or "")
                    else ""
                ),
                "size": int(stat_result.st_size or 0) if entry_type == "file" else 0,
                "file_count": 0,
                "mtime": int(stat_result.st_mtime * 1000),
                "depth": str(effect.relative_path or "").count("/") + 1
                if effect.relative_path
                else 0,
            }
        relative_path = _normalize_relative_path(
            snapshot.get("relative_path") or effect.relative_path
        )
        if relative_path != _normalize_relative_path(effect.relative_path):
            return None
        entry_type = str(snapshot.get("entry_type") or "file").lower()
        if entry_type not in {"file", "dir"}:
            return None
        parent_path = snapshot.get("parent_path")
        if parent_path is None:
            parent_path = relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
        absolute_path = str(snapshot.get("absolute_path") or "")
        if not absolute_path:
            from ..library_manager import get_library_manager

            library = get_library_manager().get_library_definition(library_id)
            if library.type == "local":
                absolute_path = os.path.join(
                    os.path.abspath(library.root_path or ""),
                    *relative_path.split("/"),
                )
        return IndexEntry(
            library_id=library_id,
            generation=int(generation),
            materialized_seq=int(materialized_seq),
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=absolute_path,
            name=str(snapshot.get("name") or relative_path.rsplit("/", 1)[-1]),
            rjcode=snapshot.get("rjcode"),
            parent_path=parent_path,
            size=max(0, int(snapshot.get("size") or 0)),
            file_count=max(0, int(snapshot.get("file_count") or 0)),
            mtime=(
                None
                if snapshot.get("mtime") is None
                else int(snapshot.get("mtime") or 0)
            ),
            depth=(
                None
                if snapshot.get("depth") is None
                else int(snapshot.get("depth") or 0)
            ),
            indexed_at=int(snapshot.get("indexed_at") or int(time.time() * 1000)),
        )

    def _estimate_fast_effect_rows(
        self,
        db,
        store: SnapshotStore,
        library_id: str,
        effect: LibraryIndexMutationEffect,
        *,
        generation: int,
    ) -> Optional[int]:
        kind = str(effect.kind or "").lower()
        if kind in {"reconcile", "replace"} and effect.scope == "subtree":
            return None
        if (
            kind == "move"
            and effect.target_library_id
            and effect.target_library_id != library_id
        ):
            return None
        if kind in {"delete", "move"}:
            if kind == "delete" and effect.scope == "exact":
                count_query = db.query(LibraryIndexEntry.id).filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.generation == generation,
                    LibraryIndexEntry.relative_path == effect.relative_path,
                )
            else:
                count_query = store._subtree_query(
                    db,
                    library_id,
                    effect.relative_path,
                    generation=generation,
                )
            row_count = int(
                count_query.with_entities(func.count(LibraryIndexEntry.id)).scalar()
                or 0
            )
            if kind == "move":
                row_count += int(
                    store._subtree_query(
                        db,
                        library_id,
                        str(effect.target_path or ""),
                        generation=generation,
                    ).with_entities(func.count(LibraryIndexEntry.id)).scalar()
                    or 0
                )
            return row_count
        if kind in {"upsert", "replace"} and effect.scope == "exact":
            return 1
        return None

    def _apply_fast_effect_in_session(
        self,
        db,
        store: SnapshotStore,
        library_id: str,
        effect: LibraryIndexMutationEffect,
        *,
        materialized_seq: int,
        generation: int,
        status_deltas: dict[str, dict[str, int]],
    ) -> Optional[int]:
        kind = str(effect.kind or "").lower()
        if kind in {"reconcile", "replace"} and effect.scope == "subtree":
            return None
        if kind == "move" and effect.target_library_id and effect.target_library_id != library_id:
            return None
        if kind in {"delete", "move"}:
            if kind == "delete":
                delete_method = (
                    store._delete_exact_in_session
                    if effect.scope == "exact"
                    else store._delete_subtree_in_session
                )
                deleted, _size, _folders, _entries = delete_method(
                    db,
                    library_id,
                    effect.relative_path,
                    generation=generation,
                    materialized_seq=materialized_seq,
                    status_delta_accumulator=status_deltas,
                )
                return int(deleted or 0)
            old_absolute_path = str(effect.payload.get("old_absolute_path") or "")
            new_absolute_path = str(effect.payload.get("new_absolute_path") or "")
            if not old_absolute_path or not new_absolute_path:
                from ..library_manager import get_library_manager

                library = get_library_manager().get_library_definition(library_id)
                if library.type != "local":
                    return None
                root = os.path.abspath(library.root_path or "")
                old_absolute_path = os.path.join(root, *effect.relative_path.split("/"))
                new_absolute_path = os.path.join(root, *str(effect.target_path or "").split("/"))
            moved = store._move_subtree_same_library_in_session(
                db,
                library_id,
                old_relative_path=effect.relative_path,
                new_relative_path=str(effect.target_path or ""),
                old_absolute_path=old_absolute_path,
                new_absolute_path=new_absolute_path,
                generation=generation,
                materialized_seq=materialized_seq,
                status_delta_accumulator=status_deltas,
            )
            if not moved:
                raise _FastPathLimitExceeded("move 未命中旧索引，转入 reconcile")
            return int(moved)
        if kind in {"upsert", "replace"} and effect.scope == "exact":
            entry = self._entry_snapshot_for_exact_effect(
                library_id,
                effect,
                generation=generation,
                materialized_seq=materialized_seq,
            )
            if entry is None:
                return None
            old = store._get_existing_stats_map(
                db,
                library_id,
                [entry.relative_path],
                generation=generation,
            )
            old_size, old_folders = old.get(entry.relative_path, (0, 0))
            new_size, new_folders = store._entry_stats(entry)
            ancestor_deltas = store._build_bulk_upsert_ancestor_deltas(
                db,
                [entry],
                insert_only=False,
            )
            written = store._upsert_one(db, entry)
            if not written:
                return 0
            store._flush_ancestor_deltas(
                db,
                ancestor_deltas,
                generation=generation,
                materialized_seq=materialized_seq,
            )
            store._apply_status_delta(
                db,
                library_id,
                size_delta=new_size - old_size,
                folder_delta=new_folders - old_folders,
                entry_delta=0 if entry.relative_path in old else 1,
                accumulator=status_deltas,
            )
            return 1
        return None

    def _complete_seq_without_recompute(
        self,
        db,
        library_id: str,
        seq: int,
        ledger_id: int,
        epoch: int,
        generation: int,
    ) -> None:
        status = db.query(LibraryIndexStatus).filter(
            LibraryIndexStatus.library_id == library_id
        ).with_for_update().one()
        if (
            status.materializer_owner != self._consumer_name
            or int(status.materializer_epoch or 0) != int(epoch)
            or int(status.active_generation or 1) != int(generation)
            or int(status.materialized_seq or 0) + 1 != int(seq)
        ):
            raise RuntimeError("库存索引 fast-path fencing 校验失败")
        ledger = db.query(LibraryIndexMutationLedger).filter(
            LibraryIndexMutationLedger.id == ledger_id
        ).with_for_update().one()
        ledger.applied_at = get_local_now()
        ledger.error = None
        ledger.next_retry_at = None
        db.query(LibraryIndexPendingMask).filter(
            LibraryIndexPendingMask.library_id == library_id,
            LibraryIndexPendingMask.ledger_seq == seq,
        ).delete(synchronize_session=False)
        status.materialized_seq = int(seq)
        status.state_revision = int(status.state_revision or 0) + 1
        status.view_revision = int(status.view_revision or 0) + 1
        status.catchup_state = (
            "catching_up" if int(status.accepted_seq or 0) > int(seq) else "idle"
        )
        status.catchup_error = None
        status.materializer_lease_until = get_local_now() + timedelta(seconds=LEASE_SECONDS)
        status.updated_at = int(time.time() * 1000)

    def _apply_fast_path_batch(
        self,
        library_id: str,
        *,
        epoch: int,
        generation: int,
        expected_seq: int,
        ledger_id: int,
    ) -> bool:
        if not self._fast_path_enabled:
            return False
        started = time.monotonic()
        with get_resource_budget_service().acquire_sync(
            "library_index_write",
            reason="library_index.materialize.fast_path",
        ):
            db = self._materializer_session()
            try:
                db.execute(text(f"SET LOCAL lock_timeout = '{FAST_PATH_LOCK_TIMEOUT_MS}ms'"))
                db.execute(text(f"SET LOCAL statement_timeout = '{FAST_PATH_STATEMENT_TIMEOUT_MS}ms'"))
                status = db.query(LibraryIndexStatus).filter(
                    LibraryIndexStatus.library_id == library_id
                ).with_for_update().one()
                if (
                    status.materializer_owner != self._consumer_name
                    or int(status.materializer_epoch or 0) != int(epoch)
                    or int(status.active_generation or 1) != int(generation)
                    or int(status.materialized_seq or 0) + 1 != int(expected_seq)
                ):
                    raise RuntimeError("库存索引 fast-path claim fencing 校验失败")
                effects = db.query(LibraryIndexMutationEffect).filter(
                    LibraryIndexMutationEffect.ledger_id == int(ledger_id)
                ).order_by(LibraryIndexMutationEffect.effect_no.asc()).all()
                if not effects or len(effects) > FAST_PATH_MAX_EFFECTS:
                    db.rollback()
                    return False
                if any(
                    effect.kind == "move"
                    and effect.target_library_id
                    and effect.target_library_id != library_id
                    for effect in effects
                ):
                    db.rollback()
                    return False
                store = self._materializer_store()
                status_deltas: dict[str, dict[str, int]] = {}
                total_rows = 0
                move_targets = {
                    (str(effect.target_path or ""), str(effect.scope or "exact"))
                    for effect in effects
                    if effect.kind == "move"
                    and str(effect.target_library_id or library_id) == library_id
                }
                executable_effects: list[LibraryIndexMutationEffect] = []
                for effect in effects:
                    if effect.kind in {"reconcile", "move_target"} and (
                        str(effect.relative_path or ""),
                        str(effect.scope or "exact"),
                    ) in move_targets:
                        continue
                    estimated_rows = self._estimate_fast_effect_rows(
                        db,
                        store,
                        library_id,
                        effect,
                        generation=generation,
                    )
                    if estimated_rows is None:
                        db.rollback()
                        return False
                    total_rows += int(estimated_rows)
                    if total_rows > FAST_PATH_MAX_ROWS:
                        raise _FastPathLimitExceeded(
                            f"ledger 行数超过 fast-path 限制: {total_rows} > {FAST_PATH_MAX_ROWS}"
                        )
                    executable_effects.append(effect)
                for effect in executable_effects:
                    affected_rows = self._apply_fast_effect_in_session(
                        db,
                        store,
                        library_id,
                        effect,
                        materialized_seq=expected_seq,
                        generation=generation,
                        status_deltas=status_deltas,
                    )
                    if affected_rows is None:
                        raise RuntimeError(
                            "库存索引 fast-path 预估后 effect 变为不可确定"
                        )
                store._flush_status_deltas(db, status_deltas)
                self._complete_seq_without_recompute(
                    db,
                    library_id,
                    expected_seq,
                    ledger_id,
                    epoch,
                    generation,
                )
                db.commit()
                self._fast_path_last_duration_ms = (time.monotonic() - started) * 1000
                self._broadcast_libraries({library_id}, "mutation_materialized_fast_path")
                return True
            except _FastPathLimitExceeded as exc:
                db.rollback()
                self._fast_path_last_fallback_reason = str(exc)
                return False
            except Exception as exc:
                db.rollback()
                self._fast_path_last_duration_ms = (time.monotonic() - started) * 1000
                if self._fast_path_timeout(exc):
                    self._fast_path_timeout_count += 1
                    self._last_fast_path_pause_until = (
                        time.monotonic() + FAST_PATH_PAUSE_SECONDS
                    )
                    self._fast_path_last_fallback_reason = (
                        f"single_library_timeout:{type(exc).__name__}"
                    )
                    raise _FastPathRetryLater(str(exc)) from exc
                raise
            finally:
                db.close()

    def _operation_has_cross_library_move(self, operation_id: str) -> bool:
        db = SessionLocal()
        try:
            return db.query(LibraryIndexMutationEffect.id).filter(
                LibraryIndexMutationEffect.operation_id == operation_id,
                LibraryIndexMutationEffect.kind == "move",
                LibraryIndexMutationEffect.target_library_id.is_not(None),
                LibraryIndexMutationEffect.target_library_id
                != LibraryIndexMutationEffect.library_id,
            ).first() is not None
        finally:
            db.close()

    @staticmethod
    def _cross_operation_is_deterministic(
        effects: list[LibraryIndexMutationEffect],
    ) -> bool:
        move_targets = Counter(
            (
                str(effect.target_library_id or ""),
                str(effect.target_path or ""),
                str(effect.scope or "exact"),
            )
            for effect in effects
            if effect.kind == "move"
            and effect.target_library_id
            and effect.target_library_id != effect.library_id
        )
        target_markers = Counter(
            (
                str(effect.library_id or ""),
                str(effect.relative_path or ""),
                str(effect.scope or "exact"),
            )
            for effect in effects
            if effect.kind in {"move_target", "reconcile"}
        )
        if not move_targets or move_targets != target_markers:
            return False
        return all(
            effect.kind in {"move", "move_target", "reconcile"}
            for effect in effects
        )

    def _apply_cross_library_operation(self, operation_id: str) -> Optional[bool]:
        """当 operation 的所有库存 ledger 都在队头时原子搬迁索引子树。"""
        if not self._fast_path_enabled:
            return False
        if self._should_pause_fast_path():
            return None
        started = time.monotonic()
        with get_resource_budget_service().acquire_sync(
            "library_index_write",
            reason="library_index.materialize.cross_library_fast_path",
        ):
            db = self._materializer_session()
            try:
                db.execute(text(f"SET LOCAL lock_timeout = '{FAST_PATH_LOCK_TIMEOUT_MS}ms'"))
                db.execute(text(f"SET LOCAL statement_timeout = '{FAST_PATH_STATEMENT_TIMEOUT_MS}ms'"))
                ledgers = db.query(LibraryIndexMutationLedger).filter(
                    LibraryIndexMutationLedger.operation_id == operation_id
                ).order_by(LibraryIndexMutationLedger.library_id.asc()).all()
                if len(ledgers) < 2:
                    db.rollback()
                    return False
                effects = db.query(LibraryIndexMutationEffect).filter(
                    LibraryIndexMutationEffect.operation_id == operation_id
                ).order_by(
                    LibraryIndexMutationEffect.library_id.asc(),
                    LibraryIndexMutationEffect.effect_no.asc(),
                ).all()
                if (
                    not effects
                    or len(effects) > FAST_PATH_MAX_EFFECTS
                    or not self._cross_operation_is_deterministic(effects)
                ):
                    db.rollback()
                    return False

                library_ids = sorted({str(ledger.library_id) for ledger in ledgers})
                statuses = db.query(LibraryIndexStatus).filter(
                    LibraryIndexStatus.library_id.in_(library_ids)
                ).order_by(LibraryIndexStatus.library_id.asc()).with_for_update().all()
                if len(statuses) != len(library_ids):
                    db.rollback()
                    return False
                status_by_library = {str(row.library_id): row for row in statuses}
                ledger_by_library = {str(row.library_id): row for row in ledgers}
                now = get_local_now()
                for library_id in library_ids:
                    status = status_by_library[library_id]
                    ledger = ledger_by_library[library_id]
                    if (
                        status.blocked_seq is not None
                        or int(status.materialized_seq or 0) + 1 != int(ledger.seq)
                        or ledger.applied_at is not None
                        or (ledger.next_retry_at and ledger.next_retry_at > now)
                    ):
                        db.rollback()
                        return None
                    owner = str(status.materializer_owner or "")
                    lease_until = status.materializer_lease_until
                    if owner and owner != self._consumer_name and lease_until and lease_until > now:
                        db.rollback()
                        return None
                    if owner != self._consumer_name or not lease_until or lease_until <= now:
                        status.materializer_epoch = int(status.materializer_epoch or 0) + 1
                    status.materializer_owner = self._consumer_name
                    status.materializer_lease_until = now + timedelta(seconds=LEASE_SECONDS)

                from ..library_manager import get_library_manager

                manager = get_library_manager()
                store = self._materializer_store()
                status_deltas: dict[str, dict[str, int]] = {}
                total_rows = 0
                prepared_moves: list[dict[str, Any]] = []
                for effect in effects:
                    if effect.kind != "move":
                        continue
                    source_library_id = str(effect.library_id)
                    target_library_id = str(effect.target_library_id or "")
                    source_status = status_by_library[source_library_id]
                    target_status = status_by_library[target_library_id]
                    source_ledger = ledger_by_library[source_library_id]
                    target_ledger = ledger_by_library[target_library_id]
                    source_library = manager.get_library_definition(source_library_id)
                    target_library = manager.get_library_definition(target_library_id)
                    if source_library.type != "local" or target_library.type != "local":
                        db.rollback()
                        return False
                    old_absolute_path = str(
                        effect.payload.get("old_absolute_path")
                        or os.path.join(
                            os.path.abspath(source_library.root_path or ""),
                            *str(effect.relative_path or "").split("/"),
                        )
                    )
                    new_absolute_path = str(
                        effect.payload.get("new_absolute_path")
                        or os.path.join(
                            os.path.abspath(target_library.root_path or ""),
                            *str(effect.target_path or "").split("/"),
                        )
                    )
                    source_count = int(
                        store._subtree_query(
                            db,
                            source_library_id,
                            effect.relative_path,
                            generation=int(source_status.active_generation or 1),
                        ).with_entities(func.count(LibraryIndexEntry.id)).scalar()
                        or 0
                    )
                    target_count = int(
                        store._subtree_query(
                            db,
                            target_library_id,
                            str(effect.target_path or ""),
                            generation=int(target_status.active_generation or 1),
                        ).with_entities(func.count(LibraryIndexEntry.id)).scalar()
                        or 0
                    )
                    total_rows += source_count + target_count
                    if total_rows > FAST_PATH_MAX_ROWS:
                        raise _FastPathLimitExceeded(
                            f"跨库 move 行数超过 fast-path 限制: {total_rows}"
                        )
                    prepared_moves.append({
                        "effect": effect,
                        "source_library_id": source_library_id,
                        "target_library_id": target_library_id,
                        "source_generation": int(source_status.active_generation or 1),
                        "target_generation": int(target_status.active_generation or 1),
                        "source_seq": int(source_ledger.seq),
                        "target_seq": int(target_ledger.seq),
                        "old_absolute_path": old_absolute_path,
                        "new_absolute_path": new_absolute_path,
                    })
                for move in prepared_moves:
                    effect = move["effect"]
                    moved = store._move_subtree_between_libraries_in_session(
                        db,
                        move["source_library_id"],
                        move["target_library_id"],
                        old_relative_path=effect.relative_path,
                        new_relative_path=str(effect.target_path or ""),
                        old_absolute_path=move["old_absolute_path"],
                        new_absolute_path=move["new_absolute_path"],
                        source_generation=move["source_generation"],
                        target_generation=move["target_generation"],
                        source_materialized_seq=move["source_seq"],
                        target_materialized_seq=move["target_seq"],
                        status_delta_accumulator=status_deltas,
                    )
                    if not moved:
                        raise _FastPathLimitExceeded(
                            "跨库 move 未命中旧索引，转入最小路径 reconcile"
                        )
                store._flush_status_deltas(db, status_deltas)
                for library_id in library_ids:
                    status = status_by_library[library_id]
                    ledger = ledger_by_library[library_id]
                    self._complete_seq_without_recompute(
                        db,
                        library_id,
                        int(ledger.seq),
                        int(ledger.id),
                        int(status.materializer_epoch or 0),
                        int(status.active_generation or 1),
                    )
                db.commit()
                self._fast_path_last_duration_ms = (time.monotonic() - started) * 1000
                self._broadcast_libraries(
                    set(library_ids),
                    "mutation_materialized_cross_library_fast_path",
                )
                return True
            except _FastPathLimitExceeded:
                db.rollback()
                return False
            except Exception as exc:
                db.rollback()
                self._fast_path_last_duration_ms = (time.monotonic() - started) * 1000
                if self._fast_path_timeout(exc):
                    self._fast_path_timeout_count += 1
                    self._last_fast_path_pause_until = (
                        time.monotonic() + FAST_PATH_PAUSE_SECONDS
                    )
                    self._fast_path_last_fallback_reason = (
                        f"cross_library_timeout:{type(exc).__name__}"
                    )
                    logger.warning(
                        "[索引追赶] 跨库 fast-path 暂时性数据库超时，等待重试 "
                        "operation=%s",
                        operation_id,
                    )
                    return None
                raise
            finally:
                db.close()

    def _delete_effect_in_chunks(
        self,
        library_id: str,
        effect: LibraryIndexMutationEffect,
        *,
        materialized_seq: int,
        generation: int,
        owner: str,
        epoch: int,
    ) -> None:
        while not self._stop_event.is_set():
            while self._should_pause_fast_path() and not self._stop_event.is_set():
                self._stop_event.wait(SWEEP_SECONDS)
            with get_resource_budget_service().acquire_sync(
                "library_index_write",
                reason="library_index.materialize_delete_chunk",
            ):
                db = self._materializer_session()
                try:
                    db.execute(
                        text(
                            f"SET LOCAL lock_timeout = '{FAST_PATH_LOCK_TIMEOUT_MS}ms'"
                        )
                    )
                    db.execute(
                        text(
                            "SET LOCAL statement_timeout = "
                            f"'{FAST_PATH_STATEMENT_TIMEOUT_MS}ms'"
                        )
                    )
                    self._validate_chunk_fence(
                        db,
                        library_id,
                        owner=owner,
                        epoch=epoch,
                        generation=generation,
                        materialized_seq=materialized_seq,
                    )
                    ids = (
                        db.query(LibraryIndexEntry.id)
                        .filter(
                            LibraryIndexEntry.library_id == library_id,
                            LibraryIndexEntry.generation == generation,
                            self._path_filter(
                                LibraryIndexEntry.relative_path,
                                effect.relative_path,
                                effect.scope,
                            ),
                        )
                        .order_by(LibraryIndexEntry.id.asc())
                        .limit(FAST_PATH_MAX_ROWS)
                        .all()
                    )
                    entry_ids = [int(row[0]) for row in ids]
                    if not entry_ids:
                        db.rollback()
                        return
                    deleted = (
                        db.query(LibraryIndexEntry)
                        .filter(LibraryIndexEntry.id.in_(entry_ids))
                        .delete(synchronize_session=False)
                    )
                    db.commit()
                    if int(deleted or 0) < FAST_PATH_MAX_ROWS:
                        return
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()
        raise RuntimeError("库存索引物化在切片删除完成前停止")

    def _apply_effect(
        self,
        library_id: str,
        effect: LibraryIndexMutationEffect,
        *,
        materialized_seq: int,
        generation: int,
        owner: str,
        epoch: int,
    ) -> None:
        if effect.kind in {"delete", "move"}:
            self._delete_effect_in_chunks(
                library_id,
                effect,
                materialized_seq=materialized_seq,
                generation=generation,
                owner=owner,
                epoch=epoch,
            )
            return
        self._reconcile_path(
            library_id,
            effect.relative_path,
            effect.scope,
            materialized_seq=materialized_seq,
            generation=generation,
            owner=owner,
            epoch=epoch,
        )

    @staticmethod
    def _validate_chunk_fence(
        db,
        library_id: str,
        *,
        owner: str,
        epoch: int,
        generation: int,
        materialized_seq: int,
    ) -> LibraryIndexStatus:
        status = db.query(LibraryIndexStatus).filter(
            LibraryIndexStatus.library_id == library_id
        ).with_for_update().one()
        if (
            status.materializer_owner != owner
            or int(status.materializer_epoch or 0) != int(epoch)
            or int(status.active_generation or 1) != int(generation)
            or int(status.materialized_seq or 0) + 1 != int(materialized_seq)
        ):
            raise RuntimeError("库存索引 materializer chunk fencing 校验失败")
        status.materializer_lease_until = get_local_now() + timedelta(seconds=LEASE_SECONDS)
        return status

    def _reconcile_path(
        self,
        library_id: str,
        relative_path: str,
        scope: str,
        *,
        materialized_seq: int,
        generation: int,
        owner: str,
        epoch: int,
        complete_callback=None,
    ) -> bool:
        from ..library_manager import get_library_manager

        library = get_library_manager().get_library_definition(library_id)
        if library.type != "local":
            return False
        root = os.path.abspath(library.root_path or "")
        target = os.path.abspath(os.path.join(root, *relative_path.split("/"))) if relative_path else root
        try:
            common = os.path.commonpath([root, target])
        except ValueError as exc:
            raise ValueError("reconcile 路径跨库存根") from exc
        if os.path.normcase(common) != os.path.normcase(root):
            raise ValueError("reconcile 路径越出库存根")
        store = self._materializer_store()

        def validate_connection(conn) -> None:
            db = Session(bind=conn, join_transaction_mode="rollback_only")
            try:
                validate_chunk_fence(db)
                db.flush()
            finally:
                db.close()

        if not os.path.exists(target):
            store.reconcile_entries(
                library_id,
                [],
                generation=generation,
                relative_path=relative_path,
                scope=scope,
                before_commit=complete_callback or validate_connection,
            )
            return complete_callback is not None

        scanner = LocalScanner()
        entries: list[IndexEntry] = []
        scan_buffer = None
        spilled = False
        try:
            # 5000 条以内留在内存并直接走 UNNEST；超限后才落盘给 staging writer。
            with get_resource_budget_service().acquire_sync(
                "disk_io_local",
                reason="library_index.reconcile_scan",
            ):
                for entry in scanner.scan_subtree(library_id, root, target):
                    entry.materialized_seq = int(materialized_seq)
                    entry.generation = int(generation)
                    if not spilled:
                        entries.append(entry)
                        if len(entries) > TARGETED_RECONCILE_MAX_ROWS:
                            scan_buffer = tempfile.TemporaryFile(
                                prefix="kikoerumanager_index_scan_"
                            )
                            for buffered_entry in entries:
                                pickle.dump(
                                    buffered_entry,
                                    scan_buffer,
                                    protocol=pickle.HIGHEST_PROTOCOL,
                                )
                            entries.clear()
                            spilled = True
                    else:
                        pickle.dump(
                            entry,
                            scan_buffer,
                            protocol=pickle.HIGHEST_PROTOCOL,
                        )

            if not spilled:
                store.reconcile_entries(
                    library_id,
                    entries,
                    generation=generation,
                    relative_path=relative_path,
                    scope=scope,
                    before_commit=complete_callback or validate_connection,
                )
                return complete_callback is not None

            scan_buffer.seek(0)
            with store.create_rebuild_writer(library_id) as writer:
                batch: list[IndexEntry] = []
                while True:
                    try:
                        batch.append(pickle.load(scan_buffer))
                    except EOFError:
                        break
                    if len(batch) >= DEFAULT_BULK_UPSERT_CHUNK_SIZE:
                        writer.stage(batch)
                        batch.clear()
                if batch:
                    writer.stage(batch)
                writer.finish_subtree_atomic(
                    generation=generation,
                    relative_path=relative_path,
                    scope=scope,
                    before_commit=complete_callback or validate_connection,
                )
            return complete_callback is not None
        finally:
            if scan_buffer is not None:
                scan_buffer.close()

    def _claim_next(self, library_id: str) -> Optional[tuple[int, int]]:
        db = self._materializer_session()
        try:
            status = self._ensure_status(db, library_id, for_update=True)
            if status.blocked_seq is not None:
                db.rollback()
                return None
            now = get_local_now()
            lease_until = status.materializer_lease_until
            owner = str(status.materializer_owner or "")
            if owner and owner != self._consumer_name and lease_until and lease_until > now:
                db.rollback()
                return None
            if owner != self._consumer_name or not lease_until or lease_until <= now:
                status.materializer_epoch = int(status.materializer_epoch or 0) + 1
            status.materializer_owner = self._consumer_name
            status.materializer_lease_until = now + timedelta(seconds=LEASE_SECONDS)
            next_seq = int(status.materialized_seq or 0) + 1
            if next_seq > int(status.accepted_seq or 0):
                status.catchup_state = "idle"
                db.commit()
                return None
            ledger = db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.library_id == library_id,
                LibraryIndexMutationLedger.seq == next_seq,
            ).first()
            if ledger is None or (ledger.next_retry_at and ledger.next_retry_at > now):
                db.commit()
                return None
            epoch = int(status.materializer_epoch or 0)
            generation = int(status.active_generation or 1)
            db.commit()
            return epoch, generation
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _peek_next_operation_id(self, library_id: str) -> Optional[str]:
        """无锁读取连续队头，只用于决定是否进入跨库原子 claim。"""
        db = SessionLocal()
        try:
            status = db.query(
                LibraryIndexStatus.materialized_seq,
                LibraryIndexStatus.accepted_seq,
                LibraryIndexStatus.blocked_seq,
            ).filter(LibraryIndexStatus.library_id == library_id).first()
            if status is None or status.blocked_seq is not None:
                return None
            next_seq = int(status.materialized_seq or 0) + 1
            if next_seq > int(status.accepted_seq or 0):
                return None
            ledger = db.query(LibraryIndexMutationLedger.operation_id).filter(
                LibraryIndexMutationLedger.library_id == library_id,
                LibraryIndexMutationLedger.seq == next_seq,
                LibraryIndexMutationLedger.applied_at.is_(None),
            ).first()
            return str(ledger.operation_id) if ledger is not None else None
        finally:
            db.close()

    def _renew_materializer_lease(
        self,
        library_id: str,
        *,
        epoch: int,
        generation: int,
        expected_seq: int,
    ) -> bool:
        db = SessionLocal()
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).with_for_update().one()
            if (
                status.materializer_owner != self._consumer_name
                or int(status.materializer_epoch or 0) != int(epoch)
                or int(status.active_generation or 1) != int(generation)
                or int(status.materialized_seq or 0) + 1 != int(expected_seq)
            ):
                db.rollback()
                return False
            status.materializer_lease_until = get_local_now() + timedelta(seconds=LEASE_SECONDS)
            db.commit()
            return True
        except Exception:
            db.rollback()
            logger.warning(
                "[索引追赶] materializer 心跳失败 library=%s seq=%s epoch=%s",
                library_id,
                expected_seq,
                epoch,
                exc_info=True,
            )
            return True
        finally:
            db.close()

    @contextmanager
    def _materializer_heartbeat(
        self,
        library_id: str,
        *,
        epoch: int,
        generation: int,
        expected_seq: int,
    ):
        stop_event = threading.Event()
        fence_lost = threading.Event()

        def run() -> None:
            while not stop_event.wait(HEARTBEAT_SECONDS):
                if not self._renew_materializer_lease(
                    library_id,
                    epoch=epoch,
                    generation=generation,
                    expected_seq=expected_seq,
                ):
                    fence_lost.set()
                    return

        heartbeat = threading.Thread(
            target=run,
            name=f"library-index-heartbeat-{library_id}",
            daemon=True,
        )
        heartbeat.start()

        def assert_fence() -> None:
            if fence_lost.is_set():
                raise RuntimeError("库存索引 materializer heartbeat fencing 校验失败")

        try:
            yield assert_fence
        finally:
            stop_event.set()
            heartbeat.join(timeout=max(1.0, float(HEARTBEAT_SECONDS) + 1.0))

    def _process_next(self, library_id: str) -> bool:
        operation_id = self._peek_next_operation_id(library_id)
        if operation_id and self._operation_has_cross_library_move(operation_id):
            cross_result = self._apply_cross_library_operation(operation_id)
            if cross_result is True:
                return True
            if cross_result is None:
                return False
        claim = self._claim_next(library_id)
        if claim is None:
            return False
        epoch, generation = claim
        db = self._materializer_session()
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).first()
            expected_seq = int(status.materialized_seq or 0) + 1
            ledger = db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.library_id == library_id,
                LibraryIndexMutationLedger.seq == expected_seq,
            ).first()
            effects = db.query(LibraryIndexMutationEffect).filter(
                LibraryIndexMutationEffect.ledger_id == ledger.id
            ).order_by(LibraryIndexMutationEffect.effect_no.asc()).all()
            ledger_id = int(ledger.id)
        finally:
            db.close()
        try:
            try:
                fast_path_applied = self._apply_fast_path_batch(
                    library_id,
                    epoch=epoch,
                    generation=generation,
                    expected_seq=expected_seq,
                    ledger_id=ledger_id,
                )
            except _FastPathRetryLater:
                return False
            if fast_path_applied:
                return True
            if any(
                effect.kind == "reconcile"
                and str(effect.relative_path or "") == ""
                and str(effect.scope or "") == "subtree"
                for effect in effects
            ):
                from ..library_manager import get_library_manager
                from .service import get_library_index_service

                library = get_library_manager().get_library_definition(library_id)
                if library.type != "local":
                    raise RuntimeError("根目录 generation recovery 仅支持本地库存")
                get_library_index_service().rebuild_local_generation(
                    library_id,
                    library.root_path,
                )
                return True
            with self._materializer_heartbeat(
                library_id,
                epoch=epoch,
                generation=generation,
                expected_seq=expected_seq,
            ) as assert_fence:
                completed_in_reconcile = False
                for index, effect in enumerate(effects):
                    assert_fence()
                    is_last = index == len(effects) - 1
                    if effect.kind not in {"delete", "move"} and is_last:
                        completed_in_reconcile = self._reconcile_path(
                            library_id,
                            effect.relative_path,
                            effect.scope,
                            materialized_seq=expected_seq,
                            generation=generation,
                            owner=self._consumer_name,
                            epoch=epoch,
                            complete_callback=lambda conn: self._complete_seq_on_connection(
                                conn,
                                library_id,
                                expected_seq,
                                ledger.id,
                                epoch,
                                generation,
                                effects,
                            ),
                        )
                    else:
                        self._apply_effect(
                            library_id,
                            effect,
                            materialized_seq=expected_seq,
                            generation=generation,
                            owner=self._consumer_name,
                            epoch=epoch,
                        )
                assert_fence()
            if completed_in_reconcile:
                self._broadcast_libraries({library_id}, "mutation_materialized")
            else:
                self._complete_seq(
                    library_id,
                    expected_seq,
                    ledger.id,
                    epoch,
                    generation,
                    effects,
                )
            return True
        except Exception as exc:
            if self._fast_path_timeout(exc):
                self._fast_path_timeout_count += 1
                self._last_fast_path_pause_until = (
                    time.monotonic() + FAST_PATH_PAUSE_SECONDS
                )
                self._fast_path_last_fallback_reason = (
                    f"slow_path_timeout:{type(exc).__name__}"
                )
                logger.warning(
                    "[索引追赶] 慢通道暂时性数据库超时，保留 ledger 等待重试 "
                    "library=%s seq=%s",
                    library_id,
                    expected_seq,
                )
                return False
            logger.exception("[索引追赶] 物化失败 library=%s seq=%s", library_id, expected_seq)
            self._record_failure(library_id, expected_seq, ledger.id, epoch, exc)
            return False

    @staticmethod
    def _ancestor_paths(relative_path: str) -> list[str]:
        current = _normalize_relative_path(relative_path)
        result: list[str] = []
        while "/" in current:
            current = current.rsplit("/", 1)[0]
            if current:
                result.append(current)
        return result

    def _complete_seq_in_session(
        self,
        db,
        library_id: str,
        seq: int,
        ledger_id: int,
        epoch: int,
        generation: int,
        effects: list[LibraryIndexMutationEffect],
    ) -> None:
        status = db.query(LibraryIndexStatus).filter(
            LibraryIndexStatus.library_id == library_id
        ).with_for_update().one()
        if (
            status.materializer_owner != self._consumer_name
            or int(status.materializer_epoch or 0) != epoch
            or int(status.active_generation or 1) != generation
            or int(status.materialized_seq or 0) + 1 != seq
        ):
            raise RuntimeError("库存索引 materializer fencing 校验失败")
        ledger = db.query(LibraryIndexMutationLedger).filter(
            LibraryIndexMutationLedger.id == ledger_id
        ).with_for_update().one()
        ledger.applied_at = get_local_now()
        ledger.error = None
        ledger.next_retry_at = None
        ancestors = sorted({
            ancestor
            for effect in effects
            for ancestor in self._ancestor_paths(effect.relative_path)
        })
        for ancestor in ancestors:
            aggregate = db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.generation == generation,
                LibraryIndexEntry.relative_path == ancestor,
                LibraryIndexEntry.entry_type == "dir",
            ).first()
            if aggregate is None:
                continue
            total_size, file_count = db.query(
                func.coalesce(
                    func.sum(
                        func.greatest(func.coalesce(LibraryIndexEntry.size, 0), 0)
                    ),
                    0,
                ),
                func.count(LibraryIndexEntry.id),
            ).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.generation == generation,
                LibraryIndexEntry.materialized_seq <= seq,
                LibraryIndexEntry.entry_type == "file",
                LibraryIndexEntry.relative_path >= ancestor + "/",
                LibraryIndexEntry.relative_path < ancestor + "0",
            ).one()
            aggregate.size = int(total_size or 0)
            aggregate.file_count = int(file_count or 0)
            aggregate.materialized_seq = seq
            aggregate.indexed_at = int(time.time() * 1000)

        total_entries, total_size_bytes, folder_count = db.query(
            func.count(LibraryIndexEntry.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LibraryIndexEntry.entry_type == "file",
                            func.greatest(func.coalesce(LibraryIndexEntry.size, 0), 0),
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.count(LibraryIndexEntry.id).filter(
                LibraryIndexEntry.entry_type == "dir",
                LibraryIndexEntry.relative_path != "",
                func.coalesce(LibraryIndexEntry.parent_path, "") == "",
            ),
        ).filter(
            LibraryIndexEntry.library_id == library_id,
            LibraryIndexEntry.generation == generation,
            LibraryIndexEntry.materialized_seq <= seq,
        ).one()
        status.total_entries = int(total_entries or 0)
        status.total_size_bytes = int(total_size_bytes or 0)
        status.folder_count = int(folder_count or 0)
        db.query(LibraryIndexPendingMask).filter(
            LibraryIndexPendingMask.library_id == library_id,
            LibraryIndexPendingMask.ledger_seq == seq,
        ).delete(synchronize_session=False)
        status.materialized_seq = seq
        status.state_revision = int(status.state_revision or 0) + 1
        status.view_revision = int(status.view_revision or 0) + 1
        status.catchup_state = (
            "catching_up" if int(status.accepted_seq or 0) > seq else "idle"
        )
        status.catchup_error = None
        status.materializer_lease_until = get_local_now() + timedelta(seconds=LEASE_SECONDS)
        status.updated_at = int(time.time() * 1000)

    def _complete_seq_on_connection(
        self,
        conn,
        library_id: str,
        seq: int,
        ledger_id: int,
        epoch: int,
        generation: int,
        effects: list[LibraryIndexMutationEffect],
    ) -> None:
        db = Session(bind=conn, join_transaction_mode="rollback_only")
        try:
            self._complete_seq_in_session(
                db,
                library_id,
                seq,
                ledger_id,
                epoch,
                generation,
                effects,
            )
            db.flush()
        finally:
            db.close()

    def _complete_seq(
        self,
        library_id: str,
        seq: int,
        ledger_id: int,
        epoch: int,
        generation: int,
        effects: list[LibraryIndexMutationEffect],
    ) -> None:
        db = self._materializer_session()
        try:
            self._complete_seq_in_session(
                db,
                library_id,
                seq,
                ledger_id,
                epoch,
                generation,
                effects,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        self._broadcast_libraries({library_id}, "mutation_materialized")

    def _record_failure(self, library_id: str, seq: int, ledger_id: int, epoch: int, exc: Exception) -> None:
        db = self._materializer_session()
        try:
            status = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id == library_id
            ).with_for_update().one()
            if status.materializer_owner != self._consumer_name or int(status.materializer_epoch or 0) != epoch:
                db.rollback()
                return
            ledger = db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.id == ledger_id
            ).with_for_update().one()
            ledger.attempt_count = int(ledger.attempt_count or 0) + 1
            ledger.error = str(exc)
            status.state_revision = int(status.state_revision or 0) + 1
            status.catchup_error = str(exc)
            if ledger.attempt_count >= MAX_ATTEMPTS:
                status.blocked_seq = seq
                status.catchup_state = "blocked"
                ledger.next_retry_at = None
            else:
                delay = RETRY_DELAYS_SECONDS[min(ledger.attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)]
                ledger.next_retry_at = get_local_now() + timedelta(seconds=delay)
                status.catchup_state = "retrying"
            status.updated_at = int(time.time() * 1000)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[索引追赶] 持久化失败状态异常 library=%s seq=%s", library_id, seq)
        finally:
            db.close()
        self._broadcast_libraries({library_id}, "mutation_retry")

    def retry_blocked(
        self,
        library_id: str,
        expected_blocked_seq: Optional[int] = None,
    ) -> dict[str, Any]:
        db = SessionLocal()
        try:
            status = self._ensure_status(db, library_id, for_update=True)
            blocked_seq = status.blocked_seq
            if expected_blocked_seq is not None and blocked_seq != int(expected_blocked_seq):
                raise ValueError(
                    f"blocked_seq 已变化: expected={int(expected_blocked_seq)} "
                    f"actual={blocked_seq}"
                )
            if blocked_seq is not None:
                ledger = db.query(LibraryIndexMutationLedger).filter(
                    LibraryIndexMutationLedger.library_id == library_id,
                    LibraryIndexMutationLedger.seq == blocked_seq,
                ).first()
                if ledger:
                    ledger.attempt_count = 0
                    ledger.next_retry_at = None
                    ledger.error = None
            status.blocked_seq = None
            status.catchup_error = None
            status.catchup_state = "catching_up"
            status.state_revision = int(status.state_revision or 0) + 1
            status.updated_at = int(time.time() * 1000)
            db.commit()
            result = status.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        self._wake_event.set()
        self._broadcast_libraries({library_id}, "mutation_retry_requested")
        return result

    def _pending_library_ids(self) -> list[str]:
        db = self._materializer_session()
        try:
            rows = db.query(LibraryIndexStatus.library_id).filter(
                LibraryIndexStatus.accepted_seq > LibraryIndexStatus.materialized_seq,
                LibraryIndexStatus.blocked_seq.is_(None),
            ).order_by(LibraryIndexStatus.library_id.asc()).all()
            return [str(row[0]) for row in rows]
        finally:
            db.close()

    def cleanup_applied_ledger(self, *, chunk_size: int = LEDGER_CLEANUP_CHUNK_SIZE) -> int:
        """清理 7 天前已应用且不再被任何 building generation 需要的 ledger。"""
        cutoff = get_local_now() - timedelta(days=LEDGER_RETENTION_DAYS)
        db = self._materializer_session()
        try:
            still_needed = exists().where(
                LibraryIndexGeneration.library_id == LibraryIndexMutationLedger.library_id,
                LibraryIndexGeneration.state.in_(("building", "scanned", "reconciling")),
                LibraryIndexGeneration.build_base_seq < LibraryIndexMutationLedger.seq,
            )
            candidates = db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.applied_at.isnot(None),
                LibraryIndexMutationLedger.applied_at < cutoff,
                ~still_needed,
            ).order_by(LibraryIndexMutationLedger.applied_at.asc(), LibraryIndexMutationLedger.id.asc()).limit(
                max(1, int(chunk_size or LEDGER_CLEANUP_CHUNK_SIZE))
            ).all()
            ids = [int(row.id) for row in candidates]
            if not ids:
                return 0
            operations = {
                str(row.operation_id)
                for row in candidates
                if int(row.id) in ids
            }
            db.query(LibraryIndexMutationLedger).filter(
                LibraryIndexMutationLedger.id.in_(ids)
            ).delete(synchronize_session=False)
            for operation_id in operations:
                remaining = db.query(LibraryIndexMutationLedger.id).filter(
                    LibraryIndexMutationLedger.operation_id == operation_id
                ).first()
                masks = db.query(LibraryIndexPendingMask.id).filter(
                    LibraryIndexPendingMask.operation_id == operation_id
                ).first()
                if remaining is None and masks is None:
                    db.query(LibraryIndexMutationOperation).filter(
                        LibraryIndexMutationOperation.operation_id == operation_id
                    ).delete(synchronize_session=False)
            db.commit()
            return len(ids)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _recovery_effects(planned_scopes: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        by_library: dict[str, dict[str, dict[str, Any]]] = {}
        for raw_scope in planned_scopes or []:
            if not isinstance(raw_scope, dict):
                continue
            library_id = str(raw_scope.get("library_id") or "").strip()
            if not library_id:
                continue
            scope = str(raw_scope.get("scope") or "subtree").strip().lower()
            if scope not in {"exact", "subtree"}:
                scope = "subtree"
            source_path = _normalize_relative_path(raw_scope.get("relative_path"))
            targets = [(library_id, source_path, scope)]
            target_library_id = str(raw_scope.get("target_library_id") or "").strip()
            if raw_scope.get("target_path") is not None and target_library_id:
                targets.append((
                    target_library_id,
                    _normalize_relative_path(raw_scope.get("target_path")),
                    scope,
                ))
            for target_lid, relative_path, reconcile_scope in targets:
                rows = by_library.setdefault(target_lid, {})
                existing = rows.get(relative_path)
                if existing is None or reconcile_scope == "subtree":
                    rows[relative_path] = {
                        "kind": "reconcile",
                        "relative_path": relative_path,
                        "scope": reconcile_scope,
                    }
        return {
            library_id: sorted(
                effects.values(),
                key=lambda effect: (effect["relative_path"].count("/"), effect["relative_path"]),
            )
            for library_id, effects in sorted(by_library.items())
            if effects
        }

    def _hint_ack_state(
        self,
        hints: Iterable[tuple[str, dict[str, Any]]],
    ) -> tuple[dict[str, int], set[tuple[str, int]]]:
        requested: dict[str, set[int]] = {}
        for _message_id, payload in hints or []:
            if not isinstance(payload, dict):
                continue
            library_id = str(payload.get("library_id") or "").strip()
            operation_id = str(payload.get("operation_id") or "").strip()
            try:
                accepted_seq = int(payload.get("accepted_seq"))
            except (TypeError, ValueError):
                continue
            if not library_id or not operation_id or accepted_seq <= 0:
                continue
            requested.setdefault(library_id, set()).add(accepted_seq)
        if not requested:
            return {}, set()
        db = SessionLocal()
        try:
            rows = db.query(
                LibraryIndexStatus.library_id,
                LibraryIndexStatus.materialized_seq,
            ).filter(LibraryIndexStatus.library_id.in_(sorted(requested))).all()
            watermarks = {str(row[0]): int(row[1] or 0) for row in rows}
            retry_rows = db.query(
                LibraryIndexMutationLedger.library_id,
                LibraryIndexMutationLedger.seq,
            ).filter(
                LibraryIndexMutationLedger.library_id.in_(sorted(requested)),
                LibraryIndexMutationLedger.attempt_count > 0,
            ).all()
            retry_seqs = {
                (str(row[0]), int(row[1]))
                for row in retry_rows
                if int(row[1]) in requested.get(str(row[0]), set())
            }
            return watermarks, retry_seqs
        finally:
            db.close()

    def _load_recovery_candidates(
        self,
        recovery_now: datetime,
        failed_operation_ids: set[str],
        active_prepared_operation_ids: set[str],
    ) -> list[dict[str, Any]]:
        db = self._materializer_session()
        try:
            prepared_cutoff = recovery_now - timedelta(seconds=PREPARED_RECOVERY_STALE_SECONDS)
            reconcile_condition = LibraryIndexMutationOperation.state == "reconcile_required"
            prepared_condition = and_(
                LibraryIndexMutationOperation.state == "prepared",
                LibraryIndexMutationOperation.updated_at <= prepared_cutoff,
            )
            if failed_operation_ids:
                failed_filter = LibraryIndexMutationOperation.operation_id.notin_(
                    sorted(failed_operation_ids)
                )
                reconcile_condition = and_(reconcile_condition, failed_filter)
                prepared_condition = and_(prepared_condition, failed_filter)
            if active_prepared_operation_ids:
                prepared_condition = and_(
                    prepared_condition,
                    LibraryIndexMutationOperation.operation_id.notin_(
                        sorted(active_prepared_operation_ids)
                    ),
                )
            query = db.query(LibraryIndexMutationOperation).filter(
                or_(
                    reconcile_condition,
                    prepared_condition,
                ),
            )
            rows = query.order_by(
                LibraryIndexMutationOperation.prepared_at.asc(),
                LibraryIndexMutationOperation.operation_id.asc(),
            ).limit(RECOVERY_BATCH_SIZE).all()
            return [
                {
                    "operation_id": row.operation_id,
                    "state": row.state,
                    "filesystem_started_at": row.filesystem_started_at,
                    "planned_scopes": list(row.planned_scopes or []),
                }
                for row in rows
            ]
        finally:
            db.close()

    def _recover_candidate(self, candidate: dict[str, Any]) -> None:
        operation_id = str(candidate["operation_id"])
        if (
            candidate.get("state") == "prepared"
            and candidate.get("filesystem_started_at") is None
        ):
            self.fail_prepared(operation_id, "启动恢复：文件系统操作尚未开始")
            return
        scopes = self._recovery_effects(candidate.get("planned_scopes") or [])
        if not scopes:
            self.fail_prepared(operation_id, "启动恢复：prepared operation 没有有效路径")
            return
        self.finalize(
            operation_id,
            actual_effects_by_library=scopes,
            actual_result={
                "recovered": True,
                "recovery_source_state": candidate.get("state"),
                "recovery_mode": "filesystem_reconcile",
                "recovery_rule": (
                    "reconcile_required_immediate"
                    if candidate.get("state") == "reconcile_required"
                    else "filesystem_started_prepared_stale_5m"
                ),
            },
        )
        self._replay_count += 1

    def _recover_prepared(self) -> None:
        recovery_now = get_local_now()
        failed_operation_ids: set[str] = set()
        while not self._stop_event.is_set():
            with self._prepared_scopes_lock:
                active_operation_ids = set(self._prepared_scopes)
            candidates = self._load_recovery_candidates(
                recovery_now,
                failed_operation_ids,
                active_operation_ids,
            )
            if not candidates:
                return
            recovered = 0
            for candidate in candidates:
                operation_id = str(candidate["operation_id"])
                try:
                    self._recover_candidate(candidate)
                    recovered += 1
                except Exception:
                    failed_operation_ids.add(operation_id)
                    logger.exception(
                        "[索引追赶] 启动恢复 operation 失败 operation_id=%s state=%s",
                        operation_id,
                        candidate.get("state"),
                    )
            if recovered == 0 and not failed_operation_ids:
                return

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._recovery_event.clear()
            self._publisher_thread = threading.Thread(
                target=self._publisher_run,
                name="library-index-redis-publisher",
                daemon=True,
            )
            self._publisher_thread.start()
            self._listener_thread = threading.Thread(
                target=self._listener_run,
                name="library-index-redis-listener",
                daemon=True,
            )
            self._listener_thread.start()
            self._thread = threading.Thread(
                target=self._run,
                name="library-index-materializer",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            publisher_thread = self._publisher_thread
            listener_thread = self._listener_thread
            self._stop_event.set()
            self._wake_event.set()
            self._recovery_event.set()
        join_timeout = max(0.1, float(timeout or 5.0))
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
        if listener_thread and listener_thread.is_alive():
            listener_thread.join(timeout=join_timeout)
        if publisher_thread and publisher_thread.is_alive():
            publisher_thread.join(timeout=join_timeout)
        if (
            self._materializer_session_factory is None
            and SessionLocal is _DEFAULT_SESSION_FACTORY
        ):
            dispose_materializer_engine()

    def _run(self) -> None:
        self._recovery_event.clear()
        try:
            self._recover_prepared()
        except Exception:
            logger.exception("[索引追赶] prepared 恢复失败")
        next_recovery_sweep_at = time.monotonic() + RECOVERY_SWEEP_SECONDS
        next_cleanup_at = time.monotonic() + LEDGER_CLEANUP_SWEEP_SECONDS
        while not self._stop_event.is_set():
            if self._recovery_event.is_set() or time.monotonic() >= next_recovery_sweep_at:
                self._recovery_event.clear()
                try:
                    self._recover_prepared()
                except Exception:
                    logger.exception("[索引追赶] 周期恢复 prepared 失败")
                next_recovery_sweep_at = time.monotonic() + RECOVERY_SWEEP_SECONDS
            if time.monotonic() >= next_cleanup_at:
                try:
                    self.cleanup_applied_ledger()
                except Exception:
                    logger.exception("[索引追赶] ledger 清理失败")
                next_cleanup_at = time.monotonic() + LEDGER_CLEANUP_SWEEP_SECONDS
            progressed = False
            if not self._should_pause_fast_path():
                for library_id in self._pending_library_ids():
                    if self._stop_event.is_set():
                        break
                    try:
                        item_progressed = self._process_next(library_id)
                    except Exception:
                        self._last_fast_path_pause_until = (
                            time.monotonic() + FAST_PATH_PAUSE_SECONDS
                        )
                        logger.exception(
                            "[索引追赶] 单库存物化异常，等待 safety sweep 重试 "
                            "library=%s",
                            library_id,
                        )
                        item_progressed = False
                    if item_progressed:
                        progressed = True
                        # 每轮只做一个 ledger，重新评估主池和业务写等待，禁止无限 drain。
                        break
            self._ack_listener_hints()
            if not progressed:
                self._wake_event.wait(SWEEP_SECONDS)
                self._wake_event.clear()

    @staticmethod
    def _broadcast_libraries(library_ids: Iterable[str], reason: str) -> None:
        from ..task_center_event_service import broadcast_library_index_status_changed

        db = SessionLocal()
        try:
            rows = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.library_id.in_(list(library_ids))
            ).all()
            for row in rows:
                broadcast_library_index_status_changed(row, reason=reason)
        except Exception:
            logger.debug("[索引] 广播 mutation 状态失败", exc_info=True)
        finally:
            db.close()

    def diagnostics(self) -> dict[str, Any]:
        db = SessionLocal()
        try:
            pending = db.query(LibraryIndexStatus).filter(
                LibraryIndexStatus.accepted_seq > LibraryIndexStatus.materialized_seq
            ).all()
            oldest_prepared = db.query(LibraryIndexMutationOperation).filter(
                LibraryIndexMutationOperation.state.in_(["prepared", "reconcile_required"])
            ).order_by(LibraryIndexMutationOperation.prepared_at.asc()).first()
            pending_rows = db.query(
                LibraryIndexMutationLedger.library_id,
                LibraryIndexMutationLedger.seq,
                LibraryIndexMutationLedger.created_at,
            ).filter(
                LibraryIndexMutationLedger.applied_at.is_(None)
            ).order_by(
                LibraryIndexMutationLedger.library_id.asc(),
                LibraryIndexMutationLedger.seq.asc(),
            ).all()
            oldest_ledger_by_library: dict[str, str] = {}
            for row in pending_rows:
                library_id = str(row.library_id or "")
                if library_id not in oldest_ledger_by_library and row.created_at:
                    oldest_ledger_by_library[library_id] = row.created_at.isoformat()
            mask_counts = dict(db.query(
                LibraryIndexPendingMask.library_id,
                func.count(LibraryIndexPendingMask.id),
            ).group_by(LibraryIndexPendingMask.library_id).all())
            return {
                "worker_alive": bool(self._thread and self._thread.is_alive()),
                "publisher_alive": bool(
                    self._publisher_thread and self._publisher_thread.is_alive()
                ),
                "listener_alive": bool(
                    self._listener_thread and self._listener_thread.is_alive()
                ),
                "listener_hint_batches": int(self._listener_hints_queue.qsize()),
                "consumer": self._consumer_name,
                "replay_count": self._replay_count,
                "fast_path": {
                    "enabled": bool(self._fast_path_enabled),
                    "max_effects": FAST_PATH_MAX_EFFECTS,
                    "max_rows": FAST_PATH_MAX_ROWS,
                    "last_duration_ms": round(self._fast_path_last_duration_ms, 3),
                    "timeout_count": int(self._fast_path_timeout_count),
                    "last_fallback_reason": self._fast_path_last_fallback_reason,
                    "paused": time.monotonic() < self._last_fast_path_pause_until,
                },
                "materializer_pool": self._materializer_pool_diagnostics(),
                "pending_libraries": [row.to_dict() for row in pending],
                "oldest_prepared_at": oldest_prepared.prepared_at.isoformat() if oldest_prepared else None,
                "oldest_ledger_by_library": oldest_ledger_by_library,
                "pending_mask_count_by_library": {
                    str(library_id): int(count or 0)
                    for library_id, count in mask_counts.items()
                },
            }
        finally:
            db.close()


_mutation_service: Optional[LibraryIndexMutationService] = None
_mutation_service_lock = threading.Lock()


def get_library_index_mutation_service() -> LibraryIndexMutationService:
    global _mutation_service
    if _mutation_service is None:
        with _mutation_service_lock:
            if _mutation_service is None:
                _mutation_service = LibraryIndexMutationService()
    return _mutation_service


def start_library_index_mutation_service() -> None:
    get_library_index_mutation_service().start()


def stop_library_index_mutation_service() -> None:
    service = _mutation_service
    if service is not None:
        service.stop()
