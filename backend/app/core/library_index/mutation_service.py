"""库存索引 mutation 账本、可见性遮罩和 PostgreSQL 驱动的顺序物化。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import and_, exists, func, or_

from ...models.database import (
    LibraryIndexEntry,
    LibraryIndexGeneration,
    LibraryIndexMutationEffect,
    LibraryIndexMutationLedger,
    LibraryIndexMutationOperation,
    LibraryIndexPendingMask,
    LibraryIndexStatus,
    SessionLocal,
    get_local_now,
)
from ..redis_service import get_redis_service
from ..resource_budget_service import get_resource_budget_service
from .local_scanner import LocalScanner
from .snapshot_store import DEFAULT_BULK_UPSERT_CHUNK_SIZE, get_snapshot_store

logger = logging.getLogger(__name__)

LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 10
SWEEP_SECONDS = 2.0
MAX_ATTEMPTS = 10
RETRY_DELAYS_SECONDS = (1, 2, 5, 10, 30, 60)
RECOVERY_BATCH_SIZE = 100
PREPARED_RECOVERY_STALE_SECONDS = 300
RECOVERY_SWEEP_SECONDS = 30.0
LEDGER_RETENTION_DAYS = 7
LEDGER_CLEANUP_SWEEP_SECONDS = 3600.0
LEDGER_CLEANUP_CHUNK_SIZE = 500


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
    if kind not in {"delete", "replace", "move", "reconcile", "upsert"}:
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
    def __init__(self) -> None:
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
        self._wake_event.set()
        return response

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
                    "kind": effect["kind"],
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
            with get_resource_budget_service().acquire_sync(
                "library_index_write",
                reason="library_index.materialize_delete",
            ):
                db = SessionLocal()
                try:
                    self._validate_chunk_fence(
                        db,
                        library_id,
                        owner=owner,
                        epoch=epoch,
                        generation=generation,
                        materialized_seq=materialized_seq,
                    )
                    q = db.query(LibraryIndexEntry).filter(
                        LibraryIndexEntry.library_id == library_id,
                        LibraryIndexEntry.generation == generation,
                    )
                    q = q.filter(self._path_filter(
                        LibraryIndexEntry.relative_path,
                        effect.relative_path,
                        effect.scope,
                    ))
                    q.delete(synchronize_session=False)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()
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
    ) -> None:
        from ..library_manager import get_library_manager

        library = get_library_manager().get_library_definition(library_id)
        if library.type != "local":
            return
        root = os.path.abspath(library.root_path or "")
        target = os.path.abspath(os.path.join(root, *relative_path.split("/"))) if relative_path else root
        try:
            common = os.path.commonpath([root, target])
        except ValueError as exc:
            raise ValueError("reconcile 路径跨库存根") from exc
        if os.path.normcase(common) != os.path.normcase(root):
            raise ValueError("reconcile 路径越出库存根")
        store = get_snapshot_store()
        def validate_chunk_fence(db) -> None:
            self._validate_chunk_fence(
                db,
                library_id,
                owner=owner,
                epoch=epoch,
                generation=generation,
                materialized_seq=materialized_seq,
            )
        if not os.path.exists(target):
            with get_resource_budget_service().acquire_sync(
                "library_index_write",
                reason="library_index.materialize_missing_path",
            ):
                db = SessionLocal()
                try:
                    validate_chunk_fence(db)
                    q = db.query(LibraryIndexEntry).filter(
                        LibraryIndexEntry.library_id == library_id,
                        LibraryIndexEntry.generation == generation,
                    )
                    q = q.filter(self._path_filter(
                        LibraryIndexEntry.relative_path,
                        relative_path,
                        scope,
                    ))
                    q.delete(synchronize_session=False)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()
            return
        scanner = LocalScanner()
        buffer = []
        seen: set[str] = set()
        for entry in scanner.scan_subtree(library_id, root, target):
            entry.materialized_seq = int(materialized_seq)
            entry.generation = int(generation)
            buffer.append(entry)
            seen.add(entry.relative_path)
            if len(buffer) >= DEFAULT_BULK_UPSERT_CHUNK_SIZE:
                store.bulk_upsert(
                    buffer,
                    maintain_status_stats=False,
                    maintain_parent_dir_stats=False,
                    before_commit=validate_chunk_fence,
                )
                buffer.clear()
        if buffer:
            store.bulk_upsert(
                buffer,
                maintain_status_stats=False,
                maintain_parent_dir_stats=False,
                before_commit=validate_chunk_fence,
            )
        if scope == "subtree":
            with get_resource_budget_service().acquire_sync(
                "library_index_write",
                reason="library_index.materialize_stale_delete",
            ):
                db = SessionLocal()
                try:
                    validate_chunk_fence(db)
                    condition = self._path_filter(
                        LibraryIndexEntry.relative_path,
                        relative_path,
                        "subtree",
                    )
                    db.query(LibraryIndexEntry).filter(
                        LibraryIndexEntry.library_id == library_id,
                        LibraryIndexEntry.generation == generation,
                        condition,
                        LibraryIndexEntry.relative_path.notin_(seen or {"\0"}),
                    ).delete(synchronize_session=False)
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()

    def _claim_next(self, library_id: str) -> Optional[tuple[int, int]]:
        db = SessionLocal()
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
        claim = self._claim_next(library_id)
        if claim is None:
            return False
        epoch, generation = claim
        db = SessionLocal()
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
        finally:
            db.close()
        try:
            with self._materializer_heartbeat(
                library_id,
                epoch=epoch,
                generation=generation,
                expected_seq=expected_seq,
            ) as assert_fence:
                for effect in effects:
                    assert_fence()
                    self._apply_effect(
                        library_id,
                        effect,
                        materialized_seq=expected_seq,
                        generation=generation,
                        owner=self._consumer_name,
                        epoch=epoch,
                    )
                assert_fence()
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

    def _complete_seq(
        self,
        library_id: str,
        seq: int,
        ledger_id: int,
        epoch: int,
        generation: int,
        effects: list[LibraryIndexMutationEffect],
    ) -> None:
        db = SessionLocal()
        try:
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
                aggregate = db.query(
                    LibraryIndexEntry,
                ).filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.generation == generation,
                    LibraryIndexEntry.relative_path == ancestor,
                    LibraryIndexEntry.entry_type == "dir",
                ).first()
                if aggregate is None:
                    continue
                totals = db.query(
                    LibraryIndexEntry.size,
                ).filter(
                    LibraryIndexEntry.library_id == library_id,
                    LibraryIndexEntry.generation == generation,
                    LibraryIndexEntry.materialized_seq <= seq,
                    LibraryIndexEntry.entry_type == "file",
                    LibraryIndexEntry.relative_path >= ancestor + "/",
                    LibraryIndexEntry.relative_path < ancestor + "0",
                ).all()
                aggregate.size = sum(max(0, int(row[0] or 0)) for row in totals)
                aggregate.file_count = len(totals)
                aggregate.materialized_seq = seq
                aggregate.indexed_at = int(time.time() * 1000)

            stats = db.query(
                LibraryIndexEntry.entry_type,
                LibraryIndexEntry.relative_path,
                LibraryIndexEntry.parent_path,
                LibraryIndexEntry.size,
            ).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.generation == generation,
                LibraryIndexEntry.materialized_seq <= seq,
            ).all()
            status.total_entries = len(stats)
            status.total_size_bytes = sum(
                max(0, int(row.size or 0)) for row in stats if row.entry_type == "file"
            )
            status.folder_count = sum(
                1
                for row in stats
                if row.entry_type == "dir"
                and bool(row.relative_path)
                and str(row.parent_path or "") == ""
            )
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
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        self._broadcast_libraries({library_id}, "mutation_materialized")

    def _record_failure(self, library_id: str, seq: int, ledger_id: int, epoch: int, exc: Exception) -> None:
        db = SessionLocal()
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

    def retry_blocked(self, library_id: str) -> dict[str, Any]:
        db = SessionLocal()
        try:
            status = self._ensure_status(db, library_id, for_update=True)
            blocked_seq = status.blocked_seq
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
        db = SessionLocal()
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
        db = SessionLocal()
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
        db = SessionLocal()
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
            self._thread = threading.Thread(
                target=self._run,
                name="library-index-materializer",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            self._stop_event.set()
            self._wake_event.set()
            self._recovery_event.set()
        if thread and thread.is_alive():
            thread.join(timeout=max(0.1, float(timeout or 5.0)))

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
            redis = get_redis_service()
            hints: list[tuple[str, dict[str, Any]]] = []
            try:
                self._reclaim_cursor, hints = redis.read_library_index_mutation_hints_sync(
                    self._consumer_name,
                    count=100,
                    block_ms=250,
                    reclaim_idle_ms=60000,
                    reclaim_cursor=self._reclaim_cursor,
                )
            except Exception:
                logger.debug("[索引追赶] Redis hint 读取失败", exc_info=True)
            progressed = False
            for library_id in self._pending_library_ids():
                while not self._stop_event.is_set() and self._process_next(library_id):
                    progressed = True
            if hints:
                try:
                    watermarks, retry_seqs = self._hint_ack_state(hints)
                    redis.ack_durable_library_index_mutation_hints_sync(
                        hints,
                        materialized_seq_by_library=watermarks,
                        retry_persisted_seqs=retry_seqs,
                    )
                except Exception:
                    logger.debug("[索引追赶] Redis hint ACK 判定失败", exc_info=True)
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
                "consumer": self._consumer_name,
                "replay_count": self._replay_count,
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
