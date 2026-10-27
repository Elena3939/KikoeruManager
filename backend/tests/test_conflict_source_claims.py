"""重试必须交接源文件占用，历史错位不能绕过其他任务的保护。"""
from uuid import uuid4

import pytest

from app.core.input_scan_repository import (
    SourceOccupied, check_input_claims, handoff_conflict_claims, path_key, source_lock,
)
from app.models.database import ConflictWork, InputSourceClaim, Task as TaskRecord


def setup_problem(db, tmp_path, *, status="waiting_manual"):
    source = str(tmp_path / "RJ14131437.7z.001")
    old_id, retry_id = str(uuid4()), str(uuid4())
    db.add(TaskRecord(
        id=old_id, type="auto_process", status=status, source_path=source,
    ))
    conflict = ConflictWork(
        id=str(uuid4()), rjcode="RJ14131437", conflict_type="EXTRACT_FAILED",
        status="PENDING", task_id=old_id, new_path=source,
        new_metadata={"failed_task_id": old_id},
    )
    db.add(conflict)
    members = [source, str(tmp_path / "RJ14131437.7z.002")]
    for path in members:
        db.add(InputSourceClaim(
            path_key=path_key(path), source_path=path, owner_type="task", owner_id=old_id,
        ))
    db.flush()
    return conflict, old_id, retry_id, members


def test_retry_hands_off_all_volumes_and_allows_archive(db_session, tmp_path):
    conflict, old_id, retry_id, members = setup_problem(db_session, tmp_path)
    handoff_conflict_claims(db_session, conflict, retry_id)
    conflict.task_id = retry_id
    db_session.flush()
    assert {row.owner_id for row in db_session.query(InputSourceClaim)} == {retry_id}
    source_lock(db_session)
    check_input_claims(db_session, members, task_id=retry_id)
    assert db_session.get(TaskRecord, old_id).status == "waiting_manual"


@pytest.mark.parametrize("proof", ["failed_task_id", "retry_origin_task_id"])
def test_archive_repairs_old_retry_handoff(db_session, tmp_path, proof):
    conflict, old_id, retry_id, members = setup_problem(db_session, tmp_path)
    conflict.task_id = retry_id
    conflict.new_metadata = {proof: old_id}
    db_session.flush()
    source_lock(db_session)
    check_input_claims(db_session, members, task_id=retry_id)
    assert {row.owner_id for row in db_session.query(InputSourceClaim)} == {retry_id}


@pytest.mark.parametrize("status", ["pending", "processing", "paused", "waiting_retry"])
def test_retry_cannot_take_running_owner(db_session, tmp_path, status):
    conflict, old_id, retry_id, _ = setup_problem(db_session, tmp_path, status=status)
    with pytest.raises(SourceOccupied) as error:
        handoff_conflict_claims(db_session, conflict, retry_id)
    assert error.value.owner_id == old_id
    assert {row.owner_id for row in db_session.query(InputSourceClaim)} == {old_id}


def test_same_path_without_retry_relationship_stays_occupied(db_session, tmp_path):
    conflict, old_id, retry_id, members = setup_problem(db_session, tmp_path)
    conflict.task_id = retry_id
    conflict.new_metadata = {}
    db_session.flush()
    source_lock(db_session)
    with pytest.raises(SourceOccupied):
        check_input_claims(db_session, members, task_id=retry_id)
    assert {row.owner_id for row in db_session.query(InputSourceClaim)} == {old_id}


def test_other_pending_problem_blocks_handoff(db_session, tmp_path):
    conflict, old_id, retry_id, members = setup_problem(db_session, tmp_path)
    db_session.add(ConflictWork(
        id=str(uuid4()), task_id=old_id, new_path=members[0],
        rjcode="RJ14131437", conflict_type="EXTRACT_FAILED", status="PENDING",
    ))
    db_session.flush()
    with pytest.raises(SourceOccupied):
        handoff_conflict_claims(db_session, conflict, retry_id)


def test_handoff_and_problem_update_roll_back_together(db_session, tmp_path):
    conflict, old_id, retry_id, _ = setup_problem(db_session, tmp_path)
    with pytest.raises(RuntimeError):
        with db_session.begin_nested():
            handoff_conflict_claims(db_session, conflict, retry_id)
            conflict.task_id = retry_id
            db_session.flush()
            raise RuntimeError("模拟问题记录提交失败")
    assert conflict.task_id == old_id
    assert {row.owner_id for row in db_session.query(InputSourceClaim)} == {old_id}
