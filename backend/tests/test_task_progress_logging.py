"""日志状态与任务真实生命周期保持一致，不根据文案推断结果。"""

import json
import logging
from unittest.mock import patch

import pytest

from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


PREFIX = "__KIKOERUMANAGER_TASK_PROGRESS__"


def snapshots(caplog):
    return [
        json.loads(record.getMessage()[len(PREFIX):])
        for record in caplog.records
        if record.getMessage().startswith(PREFIX)
    ]


def test_progress_and_completion_log_actual_status_without_event_hook(caplog, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.core.task_engine.time.monotonic", lambda: clock[0])
    caplog.set_level(logging.INFO, logger="app.core.task_engine")
    task = Task(TaskType.HTTP_DOWNLOAD, "/download/file.zip")
    task.start()
    clock[0] += 15
    task.update_progress(37, "下载完成 100%，失败 0 个")
    clock[0] += 15
    task.update_progress(100, "下载完成，成功 1 个，失败 0 个")
    before_complete = snapshots(caplog)
    assert before_complete[-2]["progress"] == 37
    assert before_complete[-1]["status"] == "processing"
    assert before_complete[-1]["progress"] == 100
    task.complete()
    final = snapshots(caplog)[-1]
    assert final["status"] == "completed"
    assert final["progress"] == 100
    assert final["task_id"] == task.id
    assert final["phase"] == "下载"
    assert final["started_at"] == task.started_at.isoformat()
    assert final["completed_at"] == task.completed_at.isoformat()


def test_partial_failure_and_pause_resume_are_structured(caplog):
    caplog.set_level(logging.INFO, logger="app.core.task_engine")
    task = Task(TaskType.HTTP_DOWNLOAD, "/download/file.zip")
    task.start()
    task.pause()
    task.resume()
    task.task_metadata["partial_success"] = True
    task.fail("部分文件成功")
    assert [row["status"] for row in snapshots(caplog)] == [
        "processing", "paused", "processing", "partial_failed",
    ]


def test_repeated_progress_does_not_duplicate_snapshot(caplog):
    caplog.set_level(logging.INFO, logger="app.core.task_engine")
    task = Task(TaskType.HTTP_DOWNLOAD, "/download/file.zip")
    task.update_progress(50, "下载中")
    task.update_progress(50, "下载中")
    assert len(snapshots(caplog)) == 1


def test_progress_snapshot_survives_log_history_and_incremental_reads(caplog, tmp_path):
    from app.api.routes import _read_log_payload

    caplog.set_level(logging.INFO, logger="app.core.task_engine")
    task = Task(TaskType.HTTP_DOWNLOAD, "/download/file.zip")
    task.start()
    path = tmp_path / "app.log"
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    lines = [formatter.format(record) for record in caplog.records if record.getMessage().startswith(PREFIX)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    offset = path.stat().st_size
    task.complete()
    last = next(record for record in reversed(caplog.records) if record.getMessage().startswith(PREFIX))
    with path.open("a", encoding="utf-8") as output:
        output.write(formatter.format(last) + "\n")
    history = _read_log_payload(str(path), 100)
    incremental = _read_log_payload(str(path), 100, offset)
    assert history["logs"][-1] == incremental["logs"][-1]
    payload = json.loads(incremental["logs"][-1].split(PREFIX, 1)[1])
    assert payload["status"] == "completed"
    assert payload["progress"] == 100


@pytest.mark.asyncio
async def test_http_cleanup_preserves_files_with_neutral_log(caplog, tmp_path):
    caplog.set_level(logging.INFO, logger="app.core.task_engine")
    path = tmp_path / "file.zip"
    path.write_bytes(b"downloaded")
    task = Task(TaskType.HTTP_DOWNLOAD, str(path), output_path=str(tmp_path))
    task.complete()
    with patch("app.config.settings.get_config"):
        await TaskEngine()._cleanup_failed_task(task)
    message = caplog.records[-1].getMessage()
    assert "status=completed" in message
    assert "失败" not in message
    assert path.read_bytes() == b"downloaded"


def test_milestones_interval_runtime_and_monotonic_progress(caplog, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('app.core.task_engine.time.monotonic', lambda: clock[0])
    caplog.set_level(logging.INFO, logger='app.core.task_engine')
    task = Task(TaskType.HTTP_DOWNLOAD, '/download/test')
    task.task_metadata['download_runtime'] = dict(speed_bytes_per_sec=123, downloaded_bytes=456,
        total_bytes=789, file_index=2, file_count=3, retry_count=1, elapsed_seconds=9)
    task.start()
    started = task.started_at
    task.update_progress(11, '文件一')
    assert len(snapshots(caplog)) == 1
    clock[0] += 15
    task.update_progress(21, '文件二')
    assert len(snapshots(caplog)) == 2
    task.update_progress(5, '新步骤')
    assert task.progress == 21
    assert task.current_step == '新步骤'
    last = snapshots(caplog)[-1]
    assert last['version'] == 2
    for key, value in task.task_metadata['download_runtime'].items():
        assert last[key] == value
    task.fail('网络断开')
    assert snapshots(caplog)[-1]['failure_reason'] == '网络断开'
    task.start()
    assert task.started_at == started


def test_download_event_preserves_runtime_without_progress_log(caplog):
    from app.core.task_center_event_service import build_task_center_event

    task = Task(TaskType.ASMR_SYNC_DOWNLOAD, '/download/test')
    runtime = dict(stage='downloading', speed_bytes_per_sec=2000, transferred_bytes=4000,
                   total_bytes=10000, current_file_index=2, total_files=4, eta_seconds=3)
    task.task_metadata['download_runtime'] = runtime
    event = build_task_center_event(task)
    assert event['runtime'] == runtime
    caplog.set_level(logging.INFO, logger='app.core.task_engine')
    task.start()
    assert snapshots(caplog)[-1]['phase'] == 'downloading'

def test_task_event_exposes_only_known_source_modes():
    from app.core.task_center_event_service import build_task_center_event

    task = Task(TaskType.HTTP_DOWNLOAD, '/download/test')
    task.task_metadata['source_modes'] = ['pikpak', 'gofile', 'pikpak', '未知来源', None]
    assert build_task_center_event(task)['source_modes'] == ['pikpak', 'gofile']
    task.task_metadata['source_modes'] = None
    assert build_task_center_event(task)['source_modes'] == []


@pytest.mark.asyncio
async def test_task_context_is_restored_on_exception(monkeypatch):
    from app.core.app_logging import current_task_id
    engine = TaskEngine()
    task = Task(TaskType.HTTP_DOWNLOAD, '/download/test')

    async def fail(current):
        assert current_task_id.get() == current.id
        raise RuntimeError('执行异常')

    monkeypatch.setattr(engine, '_process_task_with_context', fail)
    token = current_task_id.set('outer')
    try:
        with pytest.raises(RuntimeError, match='执行异常'):
            await engine._process_task(task)
        assert current_task_id.get() == 'outer'
    finally:
        current_task_id.reset(token)
