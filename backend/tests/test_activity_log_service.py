from datetime import datetime

from app.core import activity_log_service as activity_log_service_module
from app.core.activity_log_service import _build_and_write_task_lifecycle_log, write_activity_log
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


def test_circle_completion_bonus_probe_lifecycle_records_hit_items(monkeypatch):
    captured = []

    def fake_write_activity_log(**payload):
        captured.append(payload)

    monkeypatch.setattr(activity_log_service_module, "write_activity_log", fake_write_activity_log)
    monkeypatch.setattr(
        activity_log_service_module,
        "_resolve_bonus_probe_hit_items",
        lambda rjcodes: [
            {
                "rjcode": "RJ01416572",
                "title": "早期購入特典",
                "release_date": "2026-01-01",
                "maker_id": "RG00000",
                "source": "dlsite_bonus_probe",
            }
        ],
    )

    _build_and_write_task_lifecycle_log({
        "id": "task-bonus-hit",
        "status": TaskStatus.COMPLETED,
        "type": TaskType.CIRCLE_COMPLETION_BONUS_PROBE,
        "current_step": "特典探测完成，写入 1 个",
        "error_message": "",
        "task_metadata": {
            "circle_id": "circle-1",
            "circle_name": "リリムワークス/兎月りりむ。",
            "maker_id": "RG00000",
            "mode": "deep",
            "release_dates": ["2026-01-01"],
            "bonus_probe_summary": {
                "date_count": 1,
                "probe_count": 5800,
                "hit_count": 1,
                "inserted_count": 1,
                "request_count": 12,
            },
            "bonus_probe_result": {
                "dates": [
                    {
                        "release_date": "2026-01-01",
                        "probe_count": 5800,
                        "request_count": 12,
                        "hit_count": 1,
                        "inserted_count": 1,
                        "hit_rjcodes": ["RJ01416572"],
                    }
                ]
            },
        },
        "source_path": "circle-1",
        "output_path": "",
        "rjcode": "",
        "is_cancelled": False,
        "started_at": datetime(2026, 7, 5, 10, 0, 0),
        "created_at": datetime(2026, 7, 5, 10, 0, 0),
        "completed_at": datetime(2026, 7, 5, 10, 1, 0),
    })

    assert len(captured) == 1
    detail = captured[0]["detail"]
    assert captured[0]["category"] == "circle_completion"
    assert "命中 1 个" in captured[0]["summary"]
    assert "RJ01416572" in captured[0]["summary"]
    assert detail["source_action"] == "bonus_probe"
    assert detail["bonus_probe_status"] == "hit"
    assert detail["bonus_hit_rjcodes"] == ["RJ01416572"]
    assert detail["bonus_hit_items"][0]["title"] == "早期購入特典"
    assert detail["bonus_date_results"][0]["hit_rjcodes"] == ["RJ01416572"]


def test_circle_completion_bonus_probe_lifecycle_records_miss(monkeypatch):
    captured = []

    def fake_write_activity_log(**payload):
        captured.append(payload)

    monkeypatch.setattr(activity_log_service_module, "write_activity_log", fake_write_activity_log)

    _build_and_write_task_lifecycle_log({
        "id": "task-bonus-miss",
        "status": TaskStatus.COMPLETED,
        "type": TaskType.CIRCLE_COMPLETION_BONUS_PROBE,
        "current_step": "特典探测完成，写入 0 个",
        "error_message": "",
        "task_metadata": {
            "circle_id": "circle-1",
            "circle_name": "リリムワークス/兎月りりむ。",
            "maker_id": "RG00000",
            "mode": "deep",
            "release_dates": ["2026-01-02"],
            "bonus_probe_summary": {
                "date_count": 1,
                "candidate_count": 34872,
                "cached_candidate_count": 34872,
                "probe_count": 0,
                "hit_count": 0,
                "inserted_count": 0,
                "request_count": 8,
            },
            "bonus_probe_result": {
                "dates": [
                    {
                        "release_date": "2026-01-02",
                        "candidate_count": 34872,
                        "cached_candidate_count": 34872,
                        "probe_count": 0,
                        "request_count": 0,
                        "hit_count": 0,
                        "inserted_count": 0,
                        "hit_rjcodes": [],
                    }
                ]
            },
        },
        "source_path": "circle-1",
        "output_path": "",
        "rjcode": "",
        "is_cancelled": False,
        "started_at": datetime(2026, 7, 5, 10, 0, 0),
        "created_at": datetime(2026, 7, 5, 10, 0, 0),
        "completed_at": datetime(2026, 7, 5, 10, 1, 0),
    })

    assert len(captured) == 1
    detail = captured[0]["detail"]
    assert "未找到特典" in captured[0]["summary"]
    assert "候选筛选 34872 个 RJ（缓存跳过 34872 个）" in captured[0]["summary"]
    assert "实际探测 0 个 RJ" in captured[0]["summary"]
    assert detail["candidate_count"] == 34872
    assert detail["cached_candidate_count"] == 34872
    assert detail["bonus_probe_status"] == "miss"
    assert detail["bonus_hit_rjcodes"] == []
    assert detail["bonus_date_results"][0]["candidate_count"] == 34872
    assert detail["bonus_date_results"][0]["hit_count"] == 0


def test_write_activity_log_projects_searchable_text(monkeypatch):
    captured = []

    class FakeWriter:
        def enqueue(self, payload):
            captured.append(payload)

    monkeypatch.setattr("app.core.activity_log_writer.get_activity_log_writer", lambda: FakeWriter())

    write_activity_log(
        category="extract",
        action="task_finished",
        status="success",
        summary="完成 RJ123456",
        detail={"batch_id": "batch-1", "session_id": "session-1"},
        rjcode="rj123456",
        task_id="task-1",
        source_path="D:/works/RJ123456.zip",
    )

    assert captured
    text = captured[0]["searchable_text"]
    assert "完成 RJ123456" in text
    assert "D:/works/RJ123456.zip" in text
    assert "RJ123456" in text
    assert "task-1" in text
    assert "batch-1" in text
    assert "session-1" in text
