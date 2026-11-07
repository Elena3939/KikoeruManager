import json
import logging
import logging.handlers
import queue
import subprocess
import sys
from pathlib import Path

from app.core.app_logging import _BoundedQueueListener, _BoundedRotatingFileHandler, _RecentFirstQueueHandler


def test_zero_backups_still_bounds_main_log_size(tmp_path):
    log_path = tmp_path / "bounded.log"
    handler = _BoundedRotatingFileHandler(log_path, maxBytes=256, backupCount=0, encoding="utf-8")
    try:
        for index in range(100):
            handler.handle(_record(f"line-{index:03d}-" + "x" * 30))
        handler.flush()
        assert log_path.stat().st_size < 256
        content = log_path.read_text(encoding="utf-8")
        assert "line-099-" in content
        assert "line-000-" not in content
        assert not (tmp_path / "bounded.log.1").exists()
    finally:
        handler.close()


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.app_logging",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_bounded_log_queue_drops_oldest_record():
    log_queue = queue.Queue(maxsize=2)
    handler = _RecentFirstQueueHandler(log_queue)

    handler.handle(_record("first"))
    handler.handle(_record("second"))
    handler.handle(_record("third"))

    assert handler.dropped_count == 1
    assert [log_queue.get_nowait().getMessage(), log_queue.get_nowait().getMessage()] == [
        "second",
        "third",
    ]


def test_queue_listener_flushes_pending_records_on_stop(tmp_path):
    log_path = tmp_path / "app.log"
    log_queue = queue.Queue(maxsize=100)
    queue_handler = _RecentFirstQueueHandler(log_queue)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    listener = _BoundedQueueListener(log_queue, file_handler)
    test_logger = logging.Logger("test.async-writer")
    test_logger.addHandler(queue_handler)

    listener.start()
    for index in range(40):
        test_logger.info("line-%s", index)
    listener.stop()
    file_handler.close()

    content = log_path.read_text(encoding="utf-8")
    assert "INFO line-0" in content
    assert "INFO line-39" in content
    assert len(content.splitlines()) == 40


def test_async_logging_keeps_rotation_management_compatible(tmp_path):
    backend_dir = Path(__file__).resolve().parent.parent
    script = """
import json
import logging
import sys
from app.core.app_logging import configure_app_logging, force_rotate_main_log, get_app_logging_status, shutdown_app_logging

log_dir = sys.argv[1]
configure_app_logging(log_dir=log_dir, use_console=False, max_mb=1, backup_count=1)
logging.getLogger("integration").info("before-rotate")
rotate = force_rotate_main_log()
logging.getLogger("integration").info("after-rotate")
status = get_app_logging_status()
shutdown_app_logging()
print(json.dumps({"rotate": rotate, "status": status}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=backend_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["rotate"]["rotated"] is True
    assert payload["status"]["async_writer"] is True
    assert payload["status"]["listener_alive"] is True
    assert "before-rotate" in (tmp_path / "app.log.1").read_text(encoding="utf-8")
    assert "after-rotate" in (tmp_path / "app.log").read_text(encoding="utf-8")


def test_info_merge_distinguishes_parameters_and_task_context(monkeypatch):
    from app.core.app_logging import _LogNoiseFilter, _TaskContextFilter, current_task_id
    clock = [100.0]
    monkeypatch.setattr("app.core.app_logging.time.monotonic", lambda: clock[0])
    noise = _LogNoiseFilter()
    monkeypatch.setattr(noise, "_schedule_locked", lambda delay: None)
    summaries = []
    monkeypatch.setattr(noise, "_emit_summary", lambda record, message: summaries.append(message))

    def send(value, task="abcdefgh-1"):
        token = current_task_id.set(task)
        try:
            entry = _record("文件 %s")
            entry.args = (value,)
            _TaskContextFilter().filter(entry)
            return noise.filter(entry)
        finally:
            current_task_id.reset(token)

    assert send(1) is True
    assert send(1) is False
    assert send(2) is True
    assert send(1, "ijklmnop-2") is True
    clock[0] += 10
    noise.flush_expired()
    assert summaries == ["[task=abcdefgh] 文件 1 (×2)"]
    assert current_task_id.get() == ""
    noise.flush_expired(force=True)


def test_traceback_is_written_once_and_summary_has_no_stack(monkeypatch):
    from app.core.app_logging import _LogNoiseFilter
    noise = _LogNoiseFilter()
    monkeypatch.setattr(noise, "_schedule_locked", lambda delay: None)
    summaries = []
    monkeypatch.setattr(noise, "_emit_summary", lambda record, message: summaries.append((record, message)))
    accepted = []
    for index in range(100):
        try:
            raise ValueError(str(index))
        except ValueError:
            entry = _record("请求失败 %s")
            entry.args = (index,)
            entry.levelno = logging.ERROR
            entry.exc_info = sys.exc_info()
            accepted.append(noise.filter(entry))
    assert sum(accepted) == 1
    noise.flush_expired(force=True)
    assert len(summaries) == 1
    assert "60s 内出现 100 次（首次 " in summaries[0][1]
    assert summaries[0][0].exc_info is None
    assert not noise._entries


def test_fingerprint_lru_is_bounded_and_flushes_evicted_repeats(monkeypatch):
    from app.core.app_logging import _LogNoiseFilter
    noise = _LogNoiseFilter()
    monkeypatch.setattr(noise, "_schedule_locked", lambda delay: None)
    summaries = []
    monkeypatch.setattr(noise, "_emit_summary", lambda record, message: summaries.append(message))
    for i in [0, 0, *range(1, 2001)]:
        entry = _record("编号 %s")
        entry.args = (i,)
        noise.filter(entry)
    assert len(noise._entries) == 2000
    assert summaries == ["编号 0 (×2)"]
    noise.flush_expired(force=True)
