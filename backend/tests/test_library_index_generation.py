"""库存索引 generation 重建与切换的 PostgreSQL 集成测试。"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import sessionmaker

import app.core.library_index.service as service_module
import app.core.library_index.snapshot_store as snapshot_store_module
from app.core.library_index.service import LibraryIndexService
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
)
from tests.postgres_test_utils import truncate_all_tables


class _NoopBudget:
    def acquire_sync(self, *_args, **_kwargs):
        from contextlib import nullcontext

        return nullcontext()


@pytest.fixture
def generation_env(db_engine, monkeypatch, tmp_path):
    truncate_all_tables(db_engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    store = SnapshotStore(session_factory=session_factory)
    monkeypatch.setattr(service_module, "SessionLocal", session_factory)
    monkeypatch.setattr(snapshot_store_module, "get_resource_budget_service", lambda: _NoopBudget())
    monkeypatch.setenv("KIKOERUMANAGER_LIBRARY_INDEX_GENERATION_CONTRACT", "1")
    monkeypatch.setattr(
        service_module,
        "require_library_index_generation_contract_ready",
        lambda _conn: {"ready": True},
    )
    monkeypatch.setenv("KIKOERUMANAGER_LIBRARY_INDEX_DATABASE_FREE_BYTES", str(10**12))
    root = tmp_path / "library"
    root.mkdir()
    env = type("GenerationEnv", (), {})()
    env.Session = session_factory
    env.store = store
    env.service = LibraryIndexService(store=store)
    env.root = root
    yield env
    truncate_all_tables(db_engine)


def _seed_active(env, library_id: str, relative_path: str = "old.txt") -> None:
    now = int(time.time() * 1000)
    db = env.Session()
    try:
        db.add(LibraryIndexStatus(
            library_id=library_id,
            status="ready",
            watcher_mode="disabled",
            accepted_seq=0,
            materialized_seq=0,
            state_revision=0,
            view_revision=0,
            active_generation=1,
            materializer_epoch=0,
            catchup_state="idle",
            updated_at=now,
        ))
        db.add(LibraryIndexGeneration(
            library_id=library_id,
            generation=1,
            state="active",
            build_base_seq=0,
            reconciled_seq=0,
        ))
        db.add(LibraryIndexEntry(
            library_id=library_id,
            generation=1,
            materialized_seq=0,
            entry_type="file",
            relative_path=relative_path,
            absolute_path=str(env.root / relative_path),
            name=relative_path,
            name_sort_key=relative_path.casefold(),
            parent_path="",
            size=3,
            file_count=0,
            mtime=1,
            depth=1,
            indexed_at=now,
        ))
        db.commit()
    finally:
        db.close()


def test_building_generation_keeps_old_active_view_and_cutover_is_atomic(generation_env):
    env = generation_env
    library_id = "generation-library"
    _seed_active(env, library_id)
    (env.root / "new.txt").write_bytes(b"new")

    generation, base_seq = env.service._create_building_generation(library_id, str(env.root))
    assert generation == 2
    assert base_seq == 0
    assert env.store.get_entry(library_id, "old.txt") is not None
    assert env.store.get_entry(library_id, "new.txt") is None

    stats = env.service._scan_building_generation(
        library_id,
        str(env.root),
        generation,
        base_seq,
        2,
    )
    assert env.store.get_entry(library_id, "old.txt") is not None
    assert env.store.get_entry(library_id, "new.txt") is None

    status = env.service._cutover_building_generation(library_id, generation, base_seq, stats)
    assert status.active_generation == 2
    assert status.building_generation is None
    assert env.store.get_entry(library_id, "old.txt") is None
    assert env.store.get_entry(library_id, "new.txt") is not None

    db = env.Session()
    try:
        old = db.query(LibraryIndexGeneration).filter_by(
            library_id=library_id,
            generation=1,
        ).one()
        assert old.state == "retired"
        assert old.delete_after is not None
        status_row = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        assert status_row.blocked_seq is None
        assert status_row.catchup_error is None
        assert status_row.error is None
    finally:
        db.close()


def test_failed_candidate_preserves_active_generation(generation_env, monkeypatch):
    env = generation_env
    library_id = "failed-generation-library"
    _seed_active(env, library_id)

    def broken_scan(*_args, **_kwargs):
        raise OSError("scan failed")

    monkeypatch.setattr(env.service, "_scan_building_generation", broken_scan)
    with pytest.raises(OSError, match="scan failed"):
        env.service.rebuild_local_generation(library_id, str(env.root), chunk_size=2)

    status = env.store.get_status(library_id)
    assert status.active_generation == 1
    assert status.building_generation is None
    assert env.store.get_entry(library_id, "old.txt") is not None
    db = env.Session()
    try:
        candidate = db.query(LibraryIndexGeneration).filter_by(
            library_id=library_id,
            generation=2,
        ).one()
        assert candidate.state == "failed"
        assert candidate.delete_after is not None
    finally:
        db.close()


def test_generation_contract_checks_database_catalog(generation_env, monkeypatch):
    env = generation_env
    checked = []

    def reject(_conn):
        checked.append(True)
        raise RuntimeError("legacy unique still exists")

    monkeypatch.setattr(service_module, "require_library_index_generation_contract_ready", reject)
    with pytest.raises(RuntimeError, match="legacy unique"):
        env.service._create_building_generation("catalog-library", str(env.root))
    assert checked == [True]


def test_candidate_reconciles_ledger_paths_to_current_filesystem(generation_env):
    env = generation_env
    library_id = "reconciled-generation-library"
    _seed_active(env, library_id, "deleted.txt")
    (env.root / "deleted.txt").write_bytes(b"old")
    generation, base_seq = env.service._create_building_generation(library_id, str(env.root))
    env.service._scan_building_generation(library_id, str(env.root), generation, base_seq, 2)

    (env.root / "deleted.txt").unlink()
    (env.root / "created.txt").write_bytes(b"created")
    db = env.Session()
    try:
        operation = LibraryIndexMutationOperation(
            operation_id="generation-reconcile-op",
            idempotency_key="generation-reconcile-key",
            request_fingerprint="fingerprint",
            kind="reconcile",
            state="committed",
            planned_scopes=[],
            actual_result={},
        )
        db.add(operation)
        db.flush()
        ledger = LibraryIndexMutationLedger(
            operation_id=operation.operation_id,
            library_id=library_id,
            seq=1,
            kind="reconcile",
            payload={},
        )
        db.add(ledger)
        db.flush()
        for effect_no, path in enumerate(("deleted.txt", "created.txt")):
            db.add(LibraryIndexMutationEffect(
                ledger_id=ledger.id,
                operation_id=operation.operation_id,
                library_id=library_id,
                seq=1,
                effect_no=effect_no,
                kind="reconcile",
                relative_path=path,
                scope="exact",
                payload={},
            ))
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        status.accepted_seq = 1
        db.commit()
    finally:
        db.close()

    env.service._reconcile_building_generation(
        library_id,
        str(env.root),
        generation,
        base_seq,
        1,
        2,
    )
    stats = env.service._building_generation_stats(library_id, generation)
    env.service._cutover_building_generation(library_id, generation, 1, stats)

    assert env.store.get_entry(library_id, "deleted.txt") is None
    created = env.store.get_entry(library_id, "created.txt")
    assert created is not None
    assert created.materialized_seq == 1


def test_cutover_rejects_prepared_scope_for_same_library(generation_env):
    env = generation_env
    library_id = "prepared-generation-library"
    _seed_active(env, library_id)
    generation, base_seq = env.service._create_building_generation(library_id, str(env.root))
    stats = env.service._scan_building_generation(
        library_id,
        str(env.root),
        generation,
        base_seq,
        2,
    )
    db = env.Session()
    try:
        operation = LibraryIndexMutationOperation(
            operation_id="prepared-generation-op",
            idempotency_key="prepared-generation-key",
            request_fingerprint="fingerprint",
            kind="delete",
            state="prepared",
            planned_scopes=[],
            actual_result={},
        )
        db.add(operation)
        db.flush()
        db.add(LibraryIndexPendingMask(
            operation_id=operation.operation_id,
            library_id=library_id,
            effect_no=0,
            kind="delete",
            relative_path="old.txt",
            scope="exact",
        ))
        db.commit()
    finally:
        db.close()

    with pytest.raises(RuntimeError, match="prepared mutation"):
        env.service._cutover_building_generation(library_id, generation, base_seq, stats)
    assert env.store.get_status(library_id).active_generation == 1
