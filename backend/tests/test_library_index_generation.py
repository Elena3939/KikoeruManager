"""库存索引 generation 重建与切换的 PostgreSQL 集成测试。"""

from __future__ import annotations

import time
from datetime import timedelta

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
    LibraryIndexRJEntry,
    LibraryIndexStatus,
    get_local_now,
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
    monkeypatch.setattr(service_module, "get_resource_budget_service", lambda: _NoopBudget())
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


def _add_index_entry(
    env,
    *,
    library_id: str,
    generation: int,
    relative_path: str,
    rjcode: str | None = None,
    materialized_seq: int = 0,
    entry_type: str = "dir",
) -> None:
    now = int(time.time() * 1000)
    db = env.Session()
    try:
        db.add(LibraryIndexEntry(
            library_id=library_id,
            generation=generation,
            materialized_seq=materialized_seq,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(env.root / relative_path),
            name=relative_path.rsplit("/", 1)[-1],
            name_sort_key=relative_path.casefold(),
            rjcode=rjcode,
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=0,
            file_count=0,
            mtime=1,
            depth=relative_path.count("/") + 1,
            indexed_at=now,
        ))
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("scope,mask_path", [
    ("exact", "circle/RJ01570953"),
    ("subtree", "circle"),
    ("subtree", ""),
])
def test_rj_index_survives_refresh_under_pending_mask(generation_env, scope, mask_path):
    env = generation_env
    library_id = "masked-rj-library"
    path = "circle/RJ01570953"
    _seed_active(env, library_id)
    _add_index_entry(
        env, library_id=library_id, generation=1,
        relative_path=path, rjcode="RJ01570953",
    )
    with env.Session() as db:
        env.store._sync_rj_entries_in_session(db, library_id, 1)
        db.add(LibraryIndexMutationOperation(
            operation_id="masked-rj-op", idempotency_key="masked-rj-key",
            request_fingerprint="masked-rj-fingerprint", kind="reconcile",
            state="committed", planned_scopes=[], actual_result={},
        ))
        db.flush()
        db.add(LibraryIndexPendingMask(
            operation_id="masked-rj-op", library_id=library_id,
            effect_no=0, ledger_seq=1, kind="reconcile",
            relative_path=mask_path, scope=scope,
        ))
        db.commit()

    assert env.service.find_by_rjcode("RJ01570953", library_id) == []
    assert env.service.find_by_rjcodes(["RJ01570953"], library_id) == []
    with env.Session() as db:
        env.store._refresh_derived_paths_in_session(
            db, {(library_id, 1): {path}},
            materialized_seq_by_library={library_id: 0},
        )
        db.commit()
        assert db.query(LibraryIndexRJEntry).filter_by(
            library_id=library_id, generation=1, rjcode="RJ01570953",
        ).count() == 1
        db.query(LibraryIndexPendingMask).filter_by(
            operation_id="masked-rj-op",
        ).delete(synchronize_session=False)
        db.commit()

    assert [row.relative_path for row in env.service.find_by_rjcode(
        "RJ01570953", library_id,
    )] == [path]
    assert [row.relative_path for row in env.service.find_by_rjcodes(
        ["RJ01570953"], library_id,
    )] == [path]


def test_building_rj_index_survives_mask_removed_at_cutover(generation_env):
    env = generation_env
    library_id = "building-rj-library"
    path = "RJ01570953"
    _seed_active(env, library_id)
    (env.root / path).mkdir()
    generation, base_seq = env.service._create_building_generation(library_id, str(env.root))
    with env.Session() as db:
        db.add(LibraryIndexMutationOperation(
            operation_id="building-rj-op", idempotency_key="building-rj-key",
            request_fingerprint="building-rj-fingerprint", kind="reconcile",
            state="committed", planned_scopes=[], actual_result={},
        ))
        db.flush()
        db.add(LibraryIndexPendingMask(
            operation_id="building-rj-op", library_id=library_id,
            effect_no=0, ledger_seq=base_seq, kind="reconcile",
            relative_path=path, scope="subtree",
        ))
        db.commit()
    stats = env.service._scan_building_generation(
        library_id, str(env.root), generation, base_seq, 2,
    )
    assert env.service.find_by_rjcodes(["RJ01570953"], library_id) == []
    env.service._cutover_building_generation(library_id, generation, base_seq, stats)
    hits = env.service.find_by_rjcodes(["RJ01570953"], library_id)
    assert [row.relative_path for row in hits] == [path]
    assert hits[0].generation == generation


def test_find_by_rjcode_repairs_legacy_row_and_bumps_view_revision(generation_env):
    env = generation_env
    library_id = "legacy-rjcode-library"
    _seed_active(env, library_id)
    _add_index_entry(
        env,
        library_id=library_id,
        generation=1,
        relative_path="circle/[title][RJ01234567]",
    )

    hits = env.service.find_by_rjcode("RJ01234567", library_id)

    assert [item.relative_path for item in hits] == ["circle/[title][RJ01234567]"]
    status = env.store.get_status(library_id)
    assert status.state_revision == 1
    assert status.view_revision == 1


def test_backfill_missing_rjcodes_only_updates_active_visible_rows(generation_env):
    env = generation_env
    library_id = "rjcode-backfill-library"
    _seed_active(env, library_id)
    _add_index_entry(
        env,
        library_id=library_id,
        generation=1,
        relative_path="visible/RJ00000011",
    )
    _add_index_entry(
        env,
        library_id=library_id,
        generation=1,
        relative_path="future/RJ00000012",
        materialized_seq=1,
    )
    db = env.Session()
    try:
        db.add(LibraryIndexGeneration(
            library_id=library_id,
            generation=2,
            state="retired",
            build_base_seq=0,
            reconciled_seq=0,
        ))
        db.commit()
    finally:
        db.close()
    _add_index_entry(
        env,
        library_id=library_id,
        generation=2,
        relative_path="inactive/RJ00000013",
    )

    result = env.store.backfill_missing_rjcodes(limit=100)

    assert result["repaired"] == 1
    db = env.Session()
    try:
        rows = {
            (row.generation, row.relative_path): row.rjcode
            for row in db.query(LibraryIndexEntry).filter(
                LibraryIndexEntry.library_id == library_id,
                LibraryIndexEntry.relative_path.like("%RJ%"),
            )
        }
    finally:
        db.close()
    assert rows[(1, "visible/RJ00000011")] == "RJ00000011"
    assert rows[(1, "future/RJ00000012")] is None
    assert rows[(2, "inactive/RJ00000013")] is None


def test_cleanup_retired_generations_preserves_active_and_building(generation_env):
    env = generation_env
    library_id = "generation-cleanup-library"
    _seed_active(env, library_id)
    expired_at = get_local_now() - timedelta(hours=1)
    db = env.Session()
    try:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        status.building_generation = 3
        active = db.query(LibraryIndexGeneration).filter_by(
            library_id=library_id,
            generation=1,
        ).one()
        active.state = "retired"
        active.delete_after = expired_at
        db.add_all([
            LibraryIndexGeneration(
                library_id=library_id,
                generation=2,
                state="retired",
                build_base_seq=0,
                reconciled_seq=0,
                delete_after=expired_at,
            ),
            LibraryIndexGeneration(
                library_id=library_id,
                generation=3,
                state="failed",
                build_base_seq=0,
                reconciled_seq=0,
                delete_after=expired_at,
            ),
        ])
        db.commit()
    finally:
        db.close()
    _add_index_entry(
        env,
        library_id=library_id,
        generation=2,
        relative_path="retired.txt",
        entry_type="file",
    )
    _add_index_entry(
        env,
        library_id=library_id,
        generation=3,
        relative_path="building.txt",
        entry_type="file",
    )

    removed = env.service.cleanup_retired_generations(
        chunk_size=1,
        max_chunks=4,
        time_budget_seconds=10,
    )

    assert removed == 1
    db = env.Session()
    try:
        generations = {
            row.generation
            for row in db.query(LibraryIndexGeneration).filter_by(library_id=library_id)
        }
        entries = {
            row.generation
            for row in db.query(LibraryIndexEntry).filter_by(library_id=library_id)
        }
    finally:
        db.close()
    assert generations == {1, 3}
    assert 1 in entries
    assert 2 not in entries
    assert 3 in entries


def test_repair_status_statistics_recounts_only_stable_active_view(generation_env):
    env = generation_env
    library_id = "status-stats-library"
    _seed_active(env, library_id)

    result = env.service.repair_status_statistics()

    assert result["repaired"] == 1
    status = env.store.get_status(library_id)
    assert status.total_entries == 1
    assert status.total_size_bytes == 3
    assert status.folder_count == 0
    assert status.state_revision == 1

    db = env.Session()
    try:
        row = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        row.total_entries = 0
        row.accepted_seq = 1
        db.commit()
    finally:
        db.close()

    skipped = env.service.repair_status_statistics()
    assert skipped["repaired"] == 0
    assert env.store.get_status(library_id).total_entries == 0

def test_rjcode_backfill_advances_past_plain_directories_and_remembers_empty_scan(generation_env, monkeypatch):
    env = generation_env
    _seed_active(env, 'incremental')
    for path in ['plain-a', 'plain-b', 'RJ00000021']:
        _add_index_entry(env, library_id='incremental', generation=1, relative_path=path)
    first = env.store.backfill_missing_rjcodes(limit=2)
    assert first['scanned'] == 2
    assert first['repaired'] == 0
    assert first['has_more']
    second = env.store.backfill_missing_rjcodes(limit=2)
    assert second['repaired'] == 1
    assert not second['has_more']
    original_query = env.store._active_view_query
    monkeypatch.setattr(env.store, '_active_view_query', lambda *_a, **_k: pytest.fail('完成水位不应重扫候选'))
    assert env.store.backfill_missing_rjcodes(limit=2)['scanned'] == 0
    monkeypatch.setattr(env.store, '_active_view_query', original_query)


def test_rjcode_backfill_empty_candidates_do_not_acquire_write_transaction(generation_env, monkeypatch):
    env = generation_env
    _seed_active(env, 'empty-lock')
    _add_index_entry(env, library_id='empty-lock', generation=1, relative_path='plain')
    monkeypatch.setattr(env.store, '_write_session', lambda **_k: pytest.fail('空候选不得获取写事务或状态行锁'))
    batch = env.store.backfill_missing_rjcodes()
    assert batch['scanned'] == 1
    assert not batch['has_more']
    assert env.store.backfill_missing_rjcodes()['scanned'] == 0


@pytest.mark.parametrize('change', ['insert', 'rename', 'generation', 'materialized'])
def test_rjcode_backfill_restarts_when_visible_version_changes(generation_env, change):
    env = generation_env
    library_id = 'changed-' + change
    _seed_active(env, library_id)
    _add_index_entry(env, library_id=library_id, generation=1, relative_path='plain')
    assert env.store.backfill_missing_rjcodes()['repaired'] == 0
    with env.Session() as db:
        status = db.query(LibraryIndexStatus).filter_by(library_id=library_id).one()
        if change == 'rename':
            row = db.query(LibraryIndexEntry).filter_by(library_id=library_id, relative_path='plain').one()
            row.relative_path = row.name = 'RJ00000022'
            status.view_revision += 1
        elif change == 'generation':
            status.active_generation = 2
        elif change == 'materialized':
            status.accepted_seq = status.materialized_seq = 1
        else:
            status.state_revision += 1
        db.commit()
    if change != 'rename':
        _add_index_entry(env, library_id=library_id, generation=2 if change == 'generation' else 1,
                         relative_path='RJ00000022', materialized_seq=1 if change == 'materialized' else 0)
    assert env.store.backfill_missing_rjcodes()['repaired'] == 1


def test_rjcode_backfill_local_legacy_write_invalidates_completed_watermark(generation_env):
    env = generation_env
    _seed_active(env, 'legacy')
    assert env.store.backfill_missing_rjcodes()['scanned'] == 0
    with env.store._write_session() as db:
        row = db.query(LibraryIndexEntry).filter_by(library_id='legacy').one()
        row.entry_type = 'dir'
        row.name = row.relative_path = 'RJ00000023'
    assert env.store.backfill_missing_rjcodes()['repaired'] == 1


def test_rjcode_backfill_rechecks_mask_between_scan_and_publish(generation_env, monkeypatch):
    from contextlib import contextmanager
    env = generation_env
    library_id = 'concurrent-mask'
    _seed_active(env, library_id)
    _add_index_entry(env, library_id=library_id, generation=1, relative_path='RJ00000024')
    original_write = env.store._write_session
    injected = False

    @contextmanager
    def add_mask_before_publish(**kwargs):
        nonlocal injected
        if not injected:
            injected = True
            with env.Session() as db:
                db.add(LibraryIndexMutationOperation(
                    operation_id='backfill-mask', idempotency_key='backfill-mask',
                    request_fingerprint='backfill-mask', kind='reconcile', state='prepared',
                    planned_scopes=[], actual_result={},
                ))
                db.flush()
                db.add(LibraryIndexPendingMask(
                    operation_id='backfill-mask', library_id=library_id, effect_no=0,
                    kind='reconcile', relative_path='RJ00000024', scope='exact',
                ))
                db.query(LibraryIndexStatus).filter_by(library_id=library_id).update({
                    LibraryIndexStatus.view_revision: LibraryIndexStatus.view_revision + 1,
                })
                db.commit()
        with original_write(**kwargs) as db:
            yield db

    monkeypatch.setattr(env.store, '_write_session', add_mask_before_publish)
    batch = env.store.backfill_missing_rjcodes()
    assert batch['repaired'] == 0
    assert batch['has_more']
    assert env.store.backfill_missing_rjcodes()['repaired'] == 0
    with env.Session() as db:
        assert db.query(LibraryIndexEntry).filter_by(library_id=library_id, name='RJ00000024').one().rjcode is None
        db.query(LibraryIndexPendingMask).filter_by(operation_id='backfill-mask').delete()
        db.query(LibraryIndexStatus).filter_by(library_id=library_id).update({
            LibraryIndexStatus.view_revision: LibraryIndexStatus.view_revision + 1,
        })
        db.commit()
    assert env.store.backfill_missing_rjcodes()['repaired'] == 1
