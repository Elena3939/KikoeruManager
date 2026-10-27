"""验证列表不扫描大诊断、元数据不被精简回写、诊断可单独读取。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import routes
from app.core import conflict_metadata


def test_projection_skips_diagnostics_before_sanitizing():
    class UnreadableDetails(dict):
        def items(self):
            raise AssertionError("列表不应遍历诊断明细")

    details = UnreadableDetails(large="payload")
    metadata = {"work_name": "name\udcff", "extract_timing": details}
    result = conflict_metadata.conflict_list_metadata(metadata)
    assert result["work_name"] != metadata["work_name"]
    assert "extract_timing" not in result
    assert metadata["extract_timing"] is details


@pytest.mark.parametrize("include_stats", [False, True])
@pytest.mark.asyncio
async def test_list_projects_once_and_keeps_original_metadata(monkeypatch, include_stats):
    from app.core import conflict_resolution_service
    from app.models import database

    metadata = {
        "work_name": "测试作品", "extract_timing": {"steps": ["x" * 50000]},
        "progress_log": ["诊断"] * 100, "source_stats_cache": {"source": {}},
        "disguised_volume_set": {"suspect_files": ["part1"]},
    }
    conflict = SimpleNamespace(
        id="test", task_id="", rjcode="RJ123456", conflict_type="EXTRACT_FAILED",
        existing_path="", new_path="/source", new_metadata=metadata,
        status="PENDING", created_at=datetime.now(),
    )
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [conflict]
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    service = Mock()
    service.describe_conflict_async = AsyncMock(return_value={
        "existing": {}, "source": {}, "new_path_kind": "archive", "metadata": metadata,
    })
    service.get_available_actions.return_value = ["RETRY"]
    monkeypatch.setattr(conflict_resolution_service, "get_conflict_resolution_service", lambda: service)
    monkeypatch.setattr(routes, "get_task_engine", lambda: Mock())
    cleaner = Mock(wraps=conflict_metadata.safe_json_value)
    monkeypatch.setattr(conflict_metadata, "safe_json_value", cleaner)

    result = await routes.get_conflicts(include_stats=include_stats)
    item = result["conflicts"][0]
    assert item["new_metadata"] == {
        "work_name": "测试作品", "disguised_volume_set": {"suspect_files": ["part1"]},
    }
    assert item["available_actions"] == ["RETRY"]
    assert item["has_diagnostics"] is True
    assert "metadata" not in item["context"]
    cleaner.assert_called_once()
    assert conflict.new_metadata is metadata
    assert len(metadata["extract_timing"]["steps"][0]) == 50000
    db.commit.assert_not_called()
    db.close.assert_called()
    # 上下文解析仍能读取统计缓存，精简仅发生在最终输出。
    snapshot = service.describe_conflict_async.call_args.args[0]
    assert snapshot.new_metadata is metadata


def test_diagnostics_returns_full_details_and_missing_is_404():
    from fastapi import HTTPException

    db = Mock()
    metadata = {"work_name": "小字段", "extract_timing": {"steps": ["x" * 50000]}}
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(new_metadata=metadata)
    assert routes.get_conflict_diagnostics("test", db)["metadata"] == {
        "extract_timing": metadata["extract_timing"],
    }
    assert metadata["work_name"] == "小字段"
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as error:
        routes.get_conflict_diagnostics("missing", db)
    assert error.value.status_code == 404


@pytest.mark.parametrize("action", ["RETRY", "KEEP_NEW"])
@pytest.mark.asyncio
async def test_status_recovery_preserves_persisted_diagnostics(monkeypatch, action):
    from app.core import conflict_resolution_service
    from app.models import database
    from app.core.task_engine import TaskStatus

    details = {"steps": ["x" * 50000]}
    metadata = {
        "resolution_action": action, "resolution_task_state": "queued",
        "extract_timing": details,
    }
    conflict = SimpleNamespace(
        id="recover", task_id="task", rjcode="RJ123456",
        conflict_type="EXTRACT_FAILED", existing_path="", new_path="/source",
        new_metadata=metadata, status="PROCESSING", created_at=datetime.now(),
    )
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [conflict]
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    service = Mock()
    service.describe_conflict_async = AsyncMock(return_value={"existing": {}})
    service.get_available_actions.return_value = ["RETRY"]
    monkeypatch.setattr(conflict_resolution_service, "get_conflict_resolution_service", lambda: service)
    engine = Mock()
    engine.get_task.return_value = SimpleNamespace(
        id="task", status=TaskStatus.WAITING_MANUAL,
    )
    monkeypatch.setattr(routes, "get_task_engine", lambda: engine)

    item = (await routes.get_conflicts())["conflicts"][0]
    assert item["status"] == conflict.status == "PENDING"
    assert item["new_metadata"]["retry_result"] == "failed"
    assert "extract_timing" not in item["new_metadata"]
    assert conflict.new_metadata["extract_timing"] is details
    assert conflict.new_metadata["resolution_task_state"] == "failed"
    assert "retry_result" not in metadata
    db.commit.assert_called_once()


@pytest.mark.parametrize("raw,expected", [
    (None, {}), ('{"work_name": "a"}', {"work_name": "a"}),
    ("broken", {"raw_metadata": "broken"}), (["legacy"], {"raw_metadata": ["legacy"]}),
])
def test_legacy_metadata_shape(raw, expected):
    assert conflict_metadata.parse_conflict_metadata(raw) == expected
