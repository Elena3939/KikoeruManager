"""真实 PostgreSQL 与文件系统验证改名准备、接管和中断恢复。"""

import os
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core import fs_utils
from app.core.input_scan_repository import InputScanRepository, SourceOccupied, path_key
from app.core.input_source_rename import InputSourceRenamer, SourceRenameUnresolved
from app.core.input_stability import observe_sources
from app.core.task_engine import Task, TaskType
from app.models.database import InputScanEntry, InputSourceClaim, Task as TaskRecord
from app.models.database import InputScanCandidate, InputScanRun, get_local_now


@pytest.fixture
def prepared(db_session, db_engine, tmp_path):
    repository = InputScanRepository(sessionmaker(bind=db_engine))
    paths = [str(tmp_path / f"39.RJ123456.part{i}.rar") for i in (1, 2)]
    for path in paths:
        with open(path, "wb") as target:
            target.write(b"archive")
    scan_id = repository.create_run(str(tmp_path), {})
    repository.discover(scan_id, [{
        "group_key": path_key(paths[0]), "source_path": paths[0], "members": paths,
    }])
    candidate = repository.due(scan_id)[0]
    evidence, _ = observe_sources(paths, {}, checks=1, interval=0.1, needs_stability=False)
    repository.update_candidate(candidate["id"], candidate["version"], state="ready", evidence=evidence)
    candidate = repository.due(scan_id)[0]
    assert repository.claim(candidate["id"], candidate["version"])
    pairs = [(path, path.replace("39.RJ", "RJ")) for path in paths]
    return repository, candidate, pairs


def test_group_rename_hands_off_members_claims_and_evidence(prepared):
    repository, candidate, pairs = prepared
    original_version = candidate["version"]
    InputSourceRenamer(repository, candidate)(pairs)
    assert candidate["source_path"] == pairs[0][1]
    assert candidate["version"] > original_version
    assert set(candidate["members"]) == {new for _, new in pairs}
    assert set(candidate["evidence"]["fingerprints"]) == set(candidate["members"])
    assert candidate["preparation"]["normalization"]["status"] == "completed"
    assert candidate["preparation"]["source_aliases"][0]["old"] == pairs[0][0]
    with repository.session_factory() as db:
        assert {row.source_path for row in db.query(InputSourceClaim)} == set(candidate["members"])
        assert {row.source_path for row in db.query(InputScanEntry)} == set(candidate["members"])
    task = Task(TaskType.AUTO_PROCESS, candidate["source_path"])
    assert repository.commit_candidate(candidate["id"], candidate["version"], task) == task.id


def test_partial_move_recovery_finishes_only_unmoved_members(prepared, monkeypatch):
    repository, candidate, pairs = prepared
    move = fs_utils.move_path_sync

    def fail_second(old, new):
        if old == pairs[1][0]:
            raise OSError("模拟断电前移动失败")
        return move(old, new)

    monkeypatch.setattr(fs_utils, "move_path_sync", fail_second)
    with pytest.raises(SourceRenameUnresolved):
        InputSourceRenamer(repository, candidate)(pairs)
    assert os.path.exists(pairs[0][1])
    assert os.path.exists(pairs[1][0])
    with repository.session_factory() as db:
        assert db.query(InputSourceClaim).count() == 4
    monkeypatch.setattr(fs_utils, "move_path_sync", move)
    InputSourceRenamer(repository, candidate).reconcile()
    assert all(os.path.exists(new) and not os.path.exists(old) for old, new in pairs)
    assert candidate["preparation"]["normalization"]["status"] == "completed"


def test_ambiguous_recovery_keeps_both_claims_even_after_cancel(prepared, monkeypatch):
    repository, candidate, pairs = prepared
    monkeypatch.setattr(fs_utils, "move_path_sync", lambda *_: (_ for _ in ()).throw(OSError("中断")))
    with pytest.raises(SourceRenameUnresolved):
        InputSourceRenamer(repository, candidate)(pairs)
    with open(pairs[0][1], "wb") as other:
        other.write(b"other")
    with pytest.raises(SourceRenameUnresolved, match="归属不明确"):
        InputSourceRenamer(repository, candidate).reconcile()
    repository.cancel(candidate["scan_id"])
    repository.finish_cancel(candidate["scan_id"])
    with repository.session_factory() as db:
        assert db.query(InputSourceClaim).count() == 4
    with open(pairs[0][0], "rb") as source:
        assert source.read() == b"archive"
    with open(pairs[0][1], "rb") as source:
        assert source.read() == b"other"


def test_target_exists_is_rejected_before_any_move(prepared):
    repository, candidate, pairs = prepared
    with open(pairs[1][1], "wb") as other:
        other.write(b"other")
    with pytest.raises(FileExistsError):
        InputSourceRenamer(repository, candidate)(pairs)
    assert all(os.path.exists(old) for old, _ in pairs)
    assert not os.path.exists(pairs[0][1])


def test_submitted_task_source_and_stale_snapshot_follow_rename(prepared):
    repository, candidate, pairs = prepared
    task = Task(TaskType.AUTO_PROCESS, candidate["source_path"])
    task.task_metadata["input_stability"] = candidate["evidence"]
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    candidate = repository.candidate_by_id(candidate["id"])
    stale = Task(TaskType.AUTO_PROCESS, task.source_path, task_id=task.id, metadata=dict(task.task_metadata))
    InputSourceRenamer(repository, candidate, task)(pairs)
    assert task.source_path == pairs[0][1]
    assert set(task.task_metadata["input_members"]) == {new for _, new in pairs}
    stale.start()
    repository.persist_execution(stale)
    with repository.session_factory() as db:
        record = db.get(TaskRecord, task.id)
        assert record.source_path == pairs[0][1]
        assert set(record.task_metadata["input_members"]) == {new for _, new in pairs}
        assert set(record.task_metadata["input_stability"]["fingerprints"]) == {new for _, new in pairs}


def test_recovery_reopens_failed_candidate_after_identity_is_proven(prepared, monkeypatch):
    repository, candidate, pairs = prepared
    move = fs_utils.move_path_sync
    monkeypatch.setattr(fs_utils, "move_path_sync", lambda *_: (_ for _ in ()).throw(OSError("中断")))
    with pytest.raises(SourceRenameUnresolved):
        InputSourceRenamer(repository, candidate)(pairs)
    with repository.session_factory.begin() as db:
        db.get(InputScanCandidate, candidate["id"]).state = "failed"
        db.get(InputScanCandidate, candidate["id"]).deadline = get_local_now() - timedelta(seconds=1)
        db.get(InputScanRun, candidate["scan_id"]).scan_status = "completed"
    monkeypatch.setattr(fs_utils, "move_path_sync", move)
    repository.reconcile_sources()
    assert candidate["scan_id"] in repository.recoverable()
    restored = repository.candidate_by_id(candidate["id"])
    assert restored["state"] == "ready"
    assert restored["deadline"] > get_local_now()
    assert set(restored["members"]) == {new for _, new in pairs}


@pytest.mark.parametrize("status", ["processing", "paused"])
def test_reconciliation_resumes_only_tasks_paused_by_recovery(prepared, monkeypatch, status):
    repository, candidate, pairs = prepared
    task = Task(TaskType.AUTO_PROCESS, candidate["source_path"])
    task.task_metadata["input_stability"] = candidate["evidence"]
    repository.commit_candidate(candidate["id"], candidate["version"], task)
    with repository.session_factory.begin() as db:
        db.get(TaskRecord, task.id).status = status
    candidate = repository.candidate_by_id(candidate["id"])
    move = fs_utils.move_path_sync
    monkeypatch.setattr(fs_utils, "move_path_sync", lambda *_: (_ for _ in ()).throw(OSError("中断")))
    with pytest.raises(SourceRenameUnresolved):
        InputSourceRenamer(repository, candidate, task)(pairs)
    repository.reconcile_sources()
    with repository.session_factory() as db:
        assert db.get(TaskRecord, task.id).status == "paused"
    monkeypatch.setattr(fs_utils, "move_path_sync", move)
    repository.reconcile_sources()
    with repository.session_factory() as db:
        record = db.get(TaskRecord, task.id)
        assert record.status == ("pending" if status == "processing" else "paused")
        assert record.source_path == pairs[0][1]


def test_cancelled_normalization_releases_claims_only_after_reconciliation(prepared, monkeypatch):
    repository, candidate, pairs = prepared
    move = fs_utils.move_path_sync
    monkeypatch.setattr(fs_utils, "move_path_sync", lambda *_: (_ for _ in ()).throw(OSError("中断")))
    with pytest.raises(SourceRenameUnresolved):
        InputSourceRenamer(repository, candidate)(pairs)
    repository.cancel(candidate["scan_id"])
    repository.finish_cancel(candidate["scan_id"])
    monkeypatch.setattr(fs_utils, "move_path_sync", move)
    repository.reconcile_sources()
    assert repository.candidate_by_id(candidate["id"])["state"] == "cancelled"
    with repository.session_factory() as db:
        assert db.query(InputSourceClaim).count() == 0


def test_other_candidate_cannot_normalize_claimed_target(prepared):
    repository, candidate, pairs = prepared
    with repository.session_factory.begin() as db:
        db.add(InputSourceClaim(
            path_key=path_key(pairs[1][1]), source_path=pairs[1][1],
            owner_type="candidate", owner_id="other",
        ))
    with pytest.raises(SourceOccupied):
        InputSourceRenamer(repository, candidate)(pairs)
    assert all(os.path.exists(old) for old, _ in pairs)
