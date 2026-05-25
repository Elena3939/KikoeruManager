from datetime import datetime

from app.core import activity_log_service as activity_log_service_module
from app.core.activity_log_service import _build_and_write_task_lifecycle_log
from app.core.task_engine import TaskStatus, TaskType


def test_auto_process_lifecycle_uses_extract_payload_total_bytes_when_output_path_missing(tmp_path, monkeypatch):
    archive_path = tmp_path / "big.zip"
    archive_path.write_bytes(b"zip")
    captured = []

    def fake_write_activity_log(**payload):
        captured.append(payload)

    monkeypatch.setattr(activity_log_service_module, "write_activity_log", fake_write_activity_log)

    _build_and_write_task_lifecycle_log({
        "id": "task-1",
        "status": TaskStatus.COMPLETED,
        "type": TaskType.AUTO_PROCESS,
        "current_step": "已拆分为 2 个独立入库子任务",
        "error_message": "",
        "task_metadata": {
            "extract_payload_total_bytes": 123456789,
            "multi_rj_subtask_count": 2,
        },
        "source_path": str(archive_path),
        "output_path": "",
        "rjcode": "RJ00000001",
        "is_cancelled": False,
        "started_at": datetime(2026, 5, 25, 15, 0, 0),
        "created_at": datetime(2026, 5, 25, 15, 0, 0),
        "completed_at": datetime(2026, 5, 25, 15, 1, 0),
    })

    assert len(captured) == 1
    detail = captured[0]["detail"]
    assert detail["extract_output_bytes"] == 123456789
    assert detail["multi_rj_subtask_count"] == 2
    assert "解压产物 117.74 MB" in captured[0]["summary"]
