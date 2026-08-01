"""库存索引 mutation 账本与后台物化的 PostgreSQL 集成测试。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import app.core.library_index.mutation_service as mutation_module
import app.core.library_index.snapshot_store as snapshot_store_module
import app.core.library_manager as library_manager_module
from app.core.library_index.mutation_service import LibraryIndexMutationService
from app.core.library_index.snapshot_store import SnapshotStore
from app.core.library_index.types import IndexEntry
from app.models.database import (
    LibraryIndexEntry,
    LibraryIndexGeneration,
    LibraryIndexMutationEffect,
    LibraryIndexMutationLedger,
    LibraryIndexMutationOperation,
    LibraryIndexPendingMask,
    LibraryIndexStatus,
    get_local_now,
)
from tests.postgres_test_utils import truncate_all_tables


class _FakeRedis:
    def __init__(self) -> None:
        self.hints: list[tuple[str, int, str]] = []

    def publish_library_index_mutation_hint_sync(
        self,
        library_id: str,
        accepted_seq: int,
        operation_id: str,
    ) -> None:
        self.hints.append((library_id, accepted_seq, operation_id))


class _FakeBudget:
    @contextmanager
    def acquire_sync(self, _resource: str, *, reason: str = ""):
        del reason
        yield


@pytest.fixture
def mutation_env(db_engine, monkeypatch):
    truncate_all_tables(db_engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_engine,
    )
    redis = _FakeRedis()
    budget = _FakeBudget()
    store = SnapshotStore(session_factory=session_factory)

    monkeypatch.setattr(mutation_module, "SessionLocal", session_factory)
    monkeypatch.setattr(mutation_module, "get_redis_service", lambda: redis)
    monkeypatch.setattr(mutation_module, "get_resource_budget_service", lambda: budget)
    monkeypatch.setattr(mutation_module, "get_snapshot_store", lambda: store)
    monkeypatch.setattr(
        snapshot_store_module,
        "get_resource_budget_service",
        lambda: budget,
    )

    service = LibraryIndexMutationService()
    broadcasts: list[tuple[set[str], str]] = []
    monkeypatch.setattr(
        service,
        "_broadcast_libraries",
        lambda library_ids, reason: broadcasts.append((set(library_ids), reason)),
    )
    env = SimpleNamespace(
        Session=session_factory,
        service=service,
        redis=redis,
        store=store,
        broadcasts=broadcasts,
    )
    yield env
    truncate_all_tables(db_engine)


def _seed_entry(
    env,
    library_id: str,
    relative_path: str,
    *,
    entry_type: str = "file",
    size: int = 10,
    materialized_seq: int = 0,
) -> None:
    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter(
            LibraryIndexStatus.library_id == library_id
        ).first()
        if status is None:
            db.add(LibraryIndexStatus(
                library_id=library_id,
                status="ready",
                watcher_mode="disabled",
                accepted_seq=materialized_seq,
                materialized_seq=materialized_seq,
                state_revision=0,
                view_revision=0,
                active_generation=1,
                materializer_epoch=0,
                catchup_state="idle",
                updated_at=int(time.time() * 1000),
            ))
        name = relative_path.rsplit("/", 1)[-1] if relative_path else library_id
        db.add(LibraryIndexEntry(
            library_id=library_id,
            generation=1,
            materialized_seq=materialized_seq,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=f"/library/{library_id}/{relative_path}",
            name=name,
            name_sort_key=name.casefold(),
            parent_path=(
                relative_path.rsplit("/", 1)[0]
                if "/" in relative_path
                else ""
            ),
            size=size,
            file_count=0,
            mtime=1,
            depth=relative_path.count("/") + 1 if relative_path else 0,
            indexed_at=1,
        ))
        db.commit()
    finally:
        db.close()


def _prepare_and_finalize(
    service: LibraryIndexMutationService,
    *,
    library_id: str,
    idempotency_key: str,
    effect: dict,
):
    prepared = service.prepare(
        kind="test_mutation",
        effects_by_library={library_id: [effect]},
        idempotency_key=idempotency_key,
    )
    result = service.finalize(
        prepared.operation_id,
        actual_effects_by_library={library_id: [effect]},
        actual_result={"ok": True},
    )
    return prepared, result


def test_prepare_creates_immediate_mask_and_enforces_idempotency(mutation_env):
    env = mutation_env
    library_id = "prepare-lib"
    effect = {
        "kind": "delete",
        "relative_path": "folder",
        "scope": "subtree",
    }
    _seed_entry(env, library_id, "folder", entry_type="dir")
    _seed_entry(env, library_id, "folder/old.txt")

    assert env.store.get_entry(library_id, "folder/old.txt") is not None
    prepared = env.service.prepare(
        kind="delete",
        effects_by_library={library_id: [effect]},
        idempotency_key="prepare-key",
    )

    db = env.Session()
    try:
        operation = db.query(LibraryIndexMutationOperation).one()
        mask = db.query(LibraryIndexPendingMask).one()
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert operation.state == "prepared"
        assert mask.operation_id == prepared.operation_id
        assert mask.ledger_seq is None
        assert mask.relative_path == "folder"
        assert mask.scope == "subtree"
        assert status.accepted_seq == 0
        assert status.materialized_seq == 0
        assert status.catchup_state == "prepared"
        assert status.view_revision == 1
    finally:
        db.close()

    assert env.store.get_entry(library_id, "folder") is None
    assert env.store.get_entry(library_id, "folder/old.txt") is None
    assert env.service.should_suppress_watcher(library_id, "folder/old.txt") is True

    replay = env.service.prepare(
        kind="delete",
        effects_by_library={library_id: [effect]},
        idempotency_key="prepare-key",
    )
    assert replay.replayed is True
    assert replay.operation_id == prepared.operation_id

    with pytest.raises(ValueError, match="Idempotency-Key"):
        env.service.prepare(
            kind="delete",
            effects_by_library={
                library_id: [{
                    "kind": "delete",
                    "relative_path": "other",
                    "scope": "exact",
                }]
            },
            idempotency_key="prepare-key",
        )


def test_recovery_rolls_back_prepared_before_filesystem_start(mutation_env):
    env = mutation_env
    library_id = "prepared-before-fs"
    prepared = env.service.prepare(
        kind="delete",
        effects_by_library={
            library_id: [{
                "kind": "delete",
                "relative_path": "untouched.txt",
                "scope": "exact",
            }]
        },
        idempotency_key="prepared-before-fs-key",
    )

    env.service._recover_candidate({
        "operation_id": prepared.operation_id,
        "state": "prepared",
        "filesystem_started_at": None,
        "planned_scopes": [{
            "library_id": library_id,
            "kind": "delete",
            "relative_path": "untouched.txt",
            "scope": "exact",
        }],
    })

    db = env.Session()
    try:
        operation = db.query(LibraryIndexMutationOperation).filter_by(
            operation_id=prepared.operation_id
        ).one()
        assert operation.state == "failed"
        assert db.query(LibraryIndexMutationLedger).filter_by(
            operation_id=prepared.operation_id
        ).count() == 0
        assert db.query(LibraryIndexPendingMask).filter_by(
            operation_id=prepared.operation_id
        ).count() == 0
    finally:
        db.close()


def test_recovery_reconciles_prepared_after_filesystem_start(mutation_env):
    env = mutation_env
    library_id = "prepared-after-fs"
    prepared = env.service.prepare(
        kind="delete",
        effects_by_library={
            library_id: [{
                "kind": "delete",
                "relative_path": "maybe-gone.txt",
                "scope": "exact",
            }]
        },
        idempotency_key="prepared-after-fs-key",
    )
    started = env.service.mark_filesystem_started(prepared.operation_id)
    assert started["filesystem_started_at"] is not None

    env.service._recover_candidate({
        "operation_id": prepared.operation_id,
        "state": "prepared",
        "filesystem_started_at": get_local_now(),
        "planned_scopes": [{
            "library_id": library_id,
            "kind": "delete",
            "relative_path": "maybe-gone.txt",
            "scope": "exact",
        }],
    })

    db = env.Session()
    try:
        operation = db.query(LibraryIndexMutationOperation).filter_by(
            operation_id=prepared.operation_id
        ).one()
        ledger = db.query(LibraryIndexMutationLedger).filter_by(
            operation_id=prepared.operation_id
        ).one()
        effect = db.query(LibraryIndexMutationEffect).filter_by(
            ledger_id=ledger.id
        ).one()
        assert operation.state == "committed"
        assert effect.kind == "reconcile"
        assert effect.relative_path == "maybe-gone.txt"
    finally:
        db.close()


def test_finalize_assigns_per_library_sequences_and_is_replay_safe(mutation_env):
    env = mutation_env
    first_effects = {
        "library-a": [{
            "kind": "move",
            "relative_path": "source-a",
            "scope": "subtree",
            "target_library_id": "library-b",
            "target_path": "target-a",
        }],
        "library-b": [{
            "kind": "reconcile",
            "relative_path": "target-a",
            "scope": "subtree",
        }],
    }
    prepared = env.service.prepare(
        kind="cross_library_move",
        effects_by_library=first_effects,
        idempotency_key="cross-library-key",
    )
    first = env.service.finalize(
        prepared.operation_id,
        actual_effects_by_library=first_effects,
        actual_result={"moved": True},
    )

    second_prepared, second = _prepare_and_finalize(
        env.service,
        library_id="library-a",
        idempotency_key="library-a-second",
        effect={
            "kind": "delete",
            "relative_path": "next.txt",
            "scope": "exact",
        },
    )
    replay = env.service.finalize(
        prepared.operation_id,
        actual_effects_by_library={
            "library-a": [{
                "kind": "delete",
                "relative_path": "must-not-be-added",
                "scope": "exact",
            }]
        },
        actual_result={"moved": False},
    )

    assert replay == first
    assert first["operation_state"] == "committed"
    assert second["operation_id"] == second_prepared.operation_id
    assert sorted(
        (fence["library_id"], fence["accepted_seq"])
        for fence in first["index_fences"]
    ) == [("library-a", 1), ("library-b", 1)]
    assert second["index_fences"][0]["accepted_seq"] == 2

    db = env.Session()
    try:
        ledgers = db.query(LibraryIndexMutationLedger).order_by(
            LibraryIndexMutationLedger.library_id,
            LibraryIndexMutationLedger.seq,
        ).all()
        assert [(row.library_id, row.seq) for row in ledgers] == [
            ("library-a", 1),
            ("library-a", 2),
            ("library-b", 1),
        ]
        assert db.query(LibraryIndexMutationLedger).filter_by(
            operation_id=prepared.operation_id
        ).count() == 2
        assert db.query(LibraryIndexMutationEffect).filter_by(
            operation_id=prepared.operation_id
        ).count() == 2
        masks = db.query(LibraryIndexPendingMask).order_by(
            LibraryIndexPendingMask.library_id,
            LibraryIndexPendingMask.ledger_seq,
        ).all()
        assert [(row.library_id, row.ledger_seq) for row in masks] == [
            ("library-a", 1),
            ("library-a", 2),
            ("library-b", 1),
        ]
    finally:
        db.close()

    assert len(env.redis.hints) == 3


def test_concurrent_finalize_keeps_a_gapless_per_library_sequence(mutation_env):
    env = mutation_env
    library_id = "concurrent-lib"
    operations: list[str] = []
    for index in range(8):
        prepared = env.service.prepare(
            kind="delete",
            effects_by_library={
                library_id: [{
                    "kind": "delete",
                    "relative_path": f"file-{index}.txt",
                    "scope": "exact",
                }]
            },
            idempotency_key=f"concurrent-key-{index}",
        )
        operations.append(prepared.operation_id)

    def finalize(index: int):
        return env.service.finalize(
            operations[index],
            actual_effects_by_library={
                library_id: [{
                    "kind": "delete",
                    "relative_path": f"file-{index}.txt",
                    "scope": "exact",
                }]
            },
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(finalize, range(len(operations))))

    assert sorted(
        result["index_fences"][0]["accepted_seq"]
        for result in results
    ) == list(range(1, len(operations) + 1))
    db = env.Session()
    try:
        assert [
            row.seq
            for row in db.query(LibraryIndexMutationLedger).filter_by(
                library_id=library_id
            ).order_by(LibraryIndexMutationLedger.seq).all()
        ] == list(range(1, len(operations) + 1))
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert status.accepted_seq == len(operations)
        assert status.materialized_seq == 0
    finally:
        db.close()


def test_delete_materialization_removes_mask_and_duplicate_delivery_is_noop(
    mutation_env,
):
    env = mutation_env
    library_id = "delete-lib"
    _seed_entry(env, library_id, "folder", entry_type="dir")
    _seed_entry(env, library_id, "folder/child.txt")
    prepared, _result = _prepare_and_finalize(
        env.service,
        library_id=library_id,
        idempotency_key="delete-materialize",
        effect={
            "kind": "delete",
            "relative_path": "folder",
            "scope": "subtree",
        },
    )

    assert env.service._process_next(library_id) is True
    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        ledger = db.query(LibraryIndexMutationLedger).filter_by(
            operation_id=prepared.operation_id
        ).one()
        applied_at = ledger.applied_at
        assert status.accepted_seq == 1
        assert status.materialized_seq == 1
        assert status.catchup_state == "idle"
        assert applied_at is not None
        assert db.query(LibraryIndexEntry).filter_by(library_id=library_id).count() == 0
        assert db.query(LibraryIndexPendingMask).filter_by(
            library_id=library_id
        ).count() == 0
    finally:
        db.close()

    assert env.service._process_next(library_id) is False
    db = env.Session()
    try:
        ledger = db.query(LibraryIndexMutationLedger).filter_by(
            operation_id=prepared.operation_id
        ).one()
        assert ledger.applied_at == applied_at
        assert ledger.attempt_count == 0
    finally:
        db.close()


def test_reconcile_materializes_current_filesystem_state(mutation_env, monkeypatch, tmp_path):
    env = mutation_env
    library_id = "reconcile-lib"
    root = tmp_path / "library"
    target = root / "incoming"
    target.mkdir(parents=True)
    (target / "current.txt").write_bytes(b"current-content")

    _seed_entry(env, library_id, "incoming", entry_type="dir")
    _seed_entry(env, library_id, "incoming/current.txt", size=1)
    _seed_entry(env, library_id, "incoming/stale.txt", size=99)

    manager = SimpleNamespace(
        get_library_definition=lambda requested_id: SimpleNamespace(
            id=requested_id,
            type="local",
            root_path=str(root),
        )
    )
    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: manager)

    _prepared, _result = _prepare_and_finalize(
        env.service,
        library_id=library_id,
        idempotency_key="reconcile-materialize",
        effect={
            "kind": "reconcile",
            "relative_path": "incoming",
            "scope": "subtree",
        },
    )
    assert env.store.get_entry(library_id, "incoming/current.txt") is None

    assert env.service._process_next(library_id) is True
    current = env.store.get_entry(library_id, "incoming/current.txt")
    assert current is not None
    assert current.size == len(b"current-content")
    assert current.generation == 1
    assert current.materialized_seq == 1
    assert env.store.get_entry(library_id, "incoming/stale.txt") is None

    db = env.Session()
    try:
        assert db.query(LibraryIndexPendingMask).filter_by(
            library_id=library_id
        ).count() == 0
        assert db.query(LibraryIndexEntry).filter_by(
            library_id=library_id,
            relative_path="incoming/stale.txt",
        ).count() == 0
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert status.materialized_seq == 1
        assert status.total_entries == 2
        assert status.total_size_bytes == len(b"current-content")
    finally:
        db.close()


def test_reconcile_staging_handles_220k_entries_with_fixed_bind_count(mutation_env):
    env = mutation_env
    library_id = "large-reconcile-lib"
    _seed_entry(env, library_id, "", entry_type="dir")
    _seed_entry(env, library_id, "stale.txt")
    observed_bind_counts: list[int] = []

    def capture_bind_count(_conn, _cursor, statement, parameters, _context, _executemany):
        if "library_index_rebuild_stage" not in statement or not parameters:
            return
        if isinstance(parameters, dict):
            observed_bind_counts.append(len(parameters))
        elif isinstance(parameters, (list, tuple)):
            observed_bind_counts.append(len(parameters))

    event.listen(env.store.bind_engine, "before_cursor_execute", capture_bind_count)
    try:
        now = int(time.time() * 1000)
        with env.store.create_rebuild_writer(library_id, chunk_size=500) as writer:
            for start in range(0, 220_001, 500):
                batch = []
                for index in range(start, min(start + 500, 220_001)):
                    relative_path = f"bulk/file-{index:06d}.txt"
                    batch.append(IndexEntry(
                        library_id=library_id,
                        generation=1,
                        materialized_seq=1,
                        entry_type="file",
                        relative_path=relative_path,
                        absolute_path=f"/library/{library_id}/{relative_path}",
                        name=f"file-{index:06d}.txt",
                        parent_path="bulk",
                        size=1,
                        file_count=0,
                        mtime=now,
                        depth=2,
                        indexed_at=now,
                    ))
                writer.stage(batch)
            result = writer.finish_subtree_atomic(
                generation=1,
                relative_path="",
                scope="subtree",
                before_commit=lambda _conn: None,
            )
    finally:
        event.remove(env.store.bind_engine, "before_cursor_execute", capture_bind_count)

    assert result["staged"] == 220_001
    assert result["deleted"] == 2
    assert observed_bind_counts
    assert max(observed_bind_counts) <= 15

    db = env.Session()
    try:
        assert db.query(LibraryIndexEntry).filter_by(
            library_id=library_id,
            generation=1,
        ).count() == 220_001
    finally:
        db.close()


def test_poison_event_blocks_after_ten_attempts_and_retry_can_complete(
    mutation_env,
    monkeypatch,
):
    env = mutation_env
    library_id = "retry-lib"
    _prepared, _result = _prepare_and_finalize(
        env.service,
        library_id=library_id,
        idempotency_key="retry-key",
        effect={
            "kind": "delete",
            "relative_path": "missing.txt",
            "scope": "exact",
        },
    )

    original_apply = env.service._apply_effect
    should_fail = {"value": True}

    def controlled_apply(*args, **kwargs):
        if should_fail["value"]:
            raise RuntimeError("poison effect")
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(env.service, "_apply_effect", controlled_apply)
    for attempt in range(1, 11):
        assert env.service._process_next(library_id) is False
        db = env.Session()
        try:
            ledger = db.query(LibraryIndexMutationLedger).filter_by(
                library_id=library_id,
                seq=1,
            ).one()
            status = db.query(LibraryIndexStatus).filter_by(
                library_id=library_id
            ).one()
            assert ledger.attempt_count == attempt
            if attempt < 10:
                assert ledger.next_retry_at is not None
                assert status.catchup_state == "retrying"
                ledger.next_retry_at = None
                db.commit()
            else:
                assert ledger.next_retry_at is None
                assert status.blocked_seq == 1
                assert status.catchup_state == "blocked"
        finally:
            db.close()

    assert env.service._claim_next(library_id) is None
    with pytest.raises(ValueError, match="blocked_seq 已变化"):
        env.service.retry_blocked(library_id, expected_blocked_seq=287)
    db = env.Session()
    try:
        still_blocked = db.query(LibraryIndexStatus).filter_by(
            library_id=library_id
        ).one()
        assert still_blocked.blocked_seq == 1
    finally:
        db.close()

    retry_status = env.service.retry_blocked(library_id, expected_blocked_seq=1)
    assert retry_status["blocked_seq"] is None
    assert retry_status["catchup_state"] == "catching_up"
    should_fail["value"] = False
    assert env.service._process_next(library_id) is True

    db = env.Session()
    try:
        ledger = db.query(LibraryIndexMutationLedger).filter_by(
            library_id=library_id,
            seq=1,
        ).one()
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert ledger.attempt_count == 0
        assert ledger.applied_at is not None
        assert status.materialized_seq == 1
        assert status.blocked_seq is None
        assert status.catchup_error is None
    finally:
        db.close()


def test_postgres_lease_and_epoch_fence_stale_worker(mutation_env, monkeypatch):
    env = mutation_env
    library_id = "fencing-lib"
    _prepared, _result = _prepare_and_finalize(
        env.service,
        library_id=library_id,
        idempotency_key="fencing-key",
        effect={
            "kind": "delete",
            "relative_path": "gone.txt",
            "scope": "exact",
        },
    )
    stale_worker = env.service
    current_worker = LibraryIndexMutationService()
    monkeypatch.setattr(current_worker, "_broadcast_libraries", lambda *_args: None)

    stale_claim = stale_worker._claim_next(library_id)
    assert stale_claim is not None
    stale_epoch, generation = stale_claim
    assert current_worker._claim_next(library_id) is None

    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        status.materializer_lease_until = get_local_now() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    current_claim = current_worker._claim_next(library_id)
    assert current_claim is not None
    current_epoch, current_generation = current_claim
    assert current_epoch > stale_epoch
    assert current_generation == generation

    db = env.Session()
    try:
        ledger = db.query(LibraryIndexMutationLedger).filter_by(
            library_id=library_id,
            seq=1,
        ).one()
        ledger_id = ledger.id
    finally:
        db.close()

    with pytest.raises(RuntimeError, match="fencing"):
        stale_worker._complete_seq(
            library_id,
            1,
            ledger_id,
            stale_epoch,
            generation,
            [],
        )

    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        ledger = db.query(LibraryIndexMutationLedger).filter_by(id=ledger_id).one()
        assert status.materializer_owner == current_worker._consumer_name
        assert status.materializer_epoch == current_epoch
        assert status.materialized_seq == 0
        assert ledger.applied_at is None
    finally:
        db.close()

    assert current_worker._process_next(library_id) is True
    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert status.materialized_seq == 1
    finally:
        db.close()


def test_long_effect_renews_postgres_lease_during_processing(mutation_env, monkeypatch):
    env = mutation_env
    library_id = "heartbeat-lib"
    _prepare_and_finalize(
        env.service,
        library_id=library_id,
        idempotency_key="heartbeat-key",
        effect={"kind": "delete", "relative_path": "gone.txt", "scope": "exact"},
    )
    renewals = []
    original_renew = env.service._renew_materializer_lease

    def tracked_renew(*args, **kwargs):
        renewals.append(time.monotonic())
        return original_renew(*args, **kwargs)

    def slow_effect(*_args, **_kwargs):
        time.sleep(0.09)

    monkeypatch.setattr(mutation_module, "HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setattr(env.service, "_renew_materializer_lease", tracked_renew)
    monkeypatch.setattr(env.service, "_apply_effect", slow_effect)

    assert env.service._process_next(library_id) is True
    assert len(renewals) >= 2
    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert status.materialized_seq == 1
    finally:
        db.close()


def test_cleanup_applied_ledger_skips_building_generation_without_blocking_others(mutation_env):
    env = mutation_env
    old_applied_at = get_local_now() - timedelta(days=8)
    db = env.Session()
    try:
        for suffix, library_id in (("protected", "cleanup-protected"), ("free", "cleanup-free")):
            operation = LibraryIndexMutationOperation(
                operation_id=f"cleanup-{suffix}-operation",
                idempotency_key=f"cleanup-{suffix}-key",
                request_fingerprint=f"cleanup-{suffix}-fingerprint",
                kind="delete",
                state="committed",
                planned_scopes=[],
                actual_result={},
            )
            db.add(operation)
            db.flush()
            db.add(LibraryIndexMutationLedger(
                operation_id=operation.operation_id,
                library_id=library_id,
                seq=1,
                kind="delete",
                payload={},
                applied_at=old_applied_at,
            ))
        db.add(LibraryIndexGeneration(
            library_id="cleanup-protected",
            generation=2,
            state="building",
            build_base_seq=0,
            reconciled_seq=0,
        ))
        db.commit()
    finally:
        db.close()


def test_redis_wake_failure_does_not_change_committed_mutation_result(mutation_env, monkeypatch):
    env = mutation_env
    prepared = env.service.prepare(
        kind="delete",
        effects_by_library={
            "redis-down-lib": [
                {"kind": "delete", "relative_path": "gone.txt", "scope": "exact"},
            ],
        },
        idempotency_key="redis-down-key",
    )

    def fail_publish(*_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(env.redis, "publish_library_index_mutation_hint_sync", fail_publish)
    result = env.service.finalize(
        prepared.operation_id,
        actual_effects_by_library={
            "redis-down-lib": [
                {"kind": "delete", "relative_path": "gone.txt", "scope": "exact"},
            ],
        },
        actual_result={"message": "deleted"},
    )

    assert result["operation_state"] == "committed"
    db = env.Session()
    try:
        operation = db.query(LibraryIndexMutationOperation).filter_by(
            operation_id=prepared.operation_id,
        ).one()
        status = db.query(LibraryIndexStatus).filter_by(library_id="redis-down-lib").one()
        assert operation.state == "committed"
        assert status.accepted_seq == 1
        assert status.materialized_seq == 0
    finally:
        db.close()

    assert env.service.cleanup_applied_ledger(chunk_size=1) == 0
    db = env.Session()
    try:
        remaining = {
            row.library_id
            for row in db.query(LibraryIndexMutationLedger).all()
        }
        assert remaining == {"redis-down-lib"}
    finally:
        db.close()
