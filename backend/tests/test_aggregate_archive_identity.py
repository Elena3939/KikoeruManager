"""合集身份在预检、失败记录、历史展示与重试之间保持一致。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import zipfile

import pytest

from app.core.archive_identity import aggregate_archive_title, aggregate_rjcodes
from app.core.extract_service import ExtractService
from app.core.task_center_service import TaskCenterService
from app.core.task_engine import Task, TaskEngine, TaskType


CODES = ["RJ01511409", "RJ01653669", "RJ01653910", "RJ01653911", "RJ01696686", "RJ01711137"]


def aggregate_metadata():
    return {"aggregate_archive": True, "aggregate_rjcodes": list(CODES), "aggregate_rj_count": 6}


@pytest.mark.parametrize("metadata", [
    {}, {"aggregate_archive": True, "aggregate_rjcodes": CODES[:1]},
    {**aggregate_metadata(), "rjcode_lock": True},
    {"aggregate_archive": True, "aggregate_rjcodes": [CODES[0], CODES[0], "无效"]},
])
def test_single_or_locked_work_is_not_relabelled(metadata):
    assert aggregate_rjcodes(metadata) == []
    assert aggregate_archive_title(metadata, "合集.zip") == ""


@pytest.mark.asyncio
async def test_precheck_and_failure_do_not_assign_first_work_to_parent(tmp_path, monkeypatch):
    source = tmp_path / "合集.zip"
    with zipfile.ZipFile(source, "w") as archive:
        for code in CODES:
            archive.writestr(f"{code}.zip", b"inner archive")
    task = Task(TaskType.AUTO_PROCESS, str(source), rjcode=CODES[0], metadata={"inferred_rjcode": CODES[0]})
    engine = TaskEngine()
    service = ExtractService()
    assert await engine._collect_multi_rj_archive_precheck(task, service) == CODES
    assert task.rjcode is None
    assert "inferred_rjcode" not in task.task_metadata
    assert engine._get_effective_rjcode(task) == ""

    classifier = Mock()
    monkeypatch.setattr("app.core.classifier.SmartClassifier", lambda: classifier)
    # 即使解压后端又推断出单个 RJ，失败事实也属于整个合集。
    task.task_metadata["inferred_rjcode"] = CODES[0]
    engine._record_problem_work_for_extract_failure(task, CODES[0], "密码未命中")
    args = classifier._add_to_conflict_works.call_args.args
    assert args[1] is None
    assert args[4] == str(source)
    assert args[5]["aggregate_rjcodes"] == CODES
    assert args[5]["work_name"] == "合集.zip（6 个作品）"
    assert "inferred_rjcode" not in args[5]


def test_task_center_displays_historical_aggregate_without_mutating_record():
    metadata = {**aggregate_metadata(), "rjcode": CODES[0]}
    service = TaskCenterService()
    conflict = SimpleNamespace(
        id="aggregate", task_id="", conflict_type="EXTRACT_FAILED", status="PENDING",
        new_path="/downloads/合集.zip", existing_path="", new_metadata=metadata,
        rjcode=CODES[0], created_at=None,
    )
    result = service._serialize_conflict_item(conflict)
    assert result["title"] == "合集.zip（6 个作品）"
    assert result["rjcode"] == ""
    assert conflict.rjcode == CODES[0]
    task = Task(TaskType.AUTO_PROCESS, conflict.new_path, rjcode=CODES[0], metadata=metadata)
    result = service._serialize_engine_task(task, mode="summary")
    assert result["title"] == "合集.zip（6 个作品）"
    assert result["rjcode"] == ""
    assert {"label": "包含作品", "value": "、".join(CODES)} in result["metrics"]


@pytest.mark.asyncio
async def test_retry_preserves_aggregate_and_does_not_restore_first_rj(tmp_path, monkeypatch):
    from app.api import routes
    from app.models import database

    source = tmp_path / "合集.zip"
    source.write_bytes(b"archive")
    conflict = SimpleNamespace(
        id="aggregate", task_id="", status="PENDING", conflict_type="EXTRACT_FAILED",
        new_path=str(source), rjcode=CODES[0], new_metadata=aggregate_metadata(),
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conflict
    engine = SimpleNamespace(get_all_tasks=lambda: [], submit=AsyncMock())
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)
    result = await routes.retry_extract_failed_conflict(conflict.id)
    assert result["success"]
    task = engine.submit.call_args.args[0]
    assert task.rjcode is None
    assert aggregate_rjcodes(task.task_metadata) == CODES
    assert "inferred_rjcode" not in task.task_metadata
    assert task.task_metadata["skip_retry_precheck"] is True
