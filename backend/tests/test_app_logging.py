import json
import logging
import logging.handlers
import queue
import subprocess
import sys
from pathlib import Path

from app.core.app_logging import _BoundedQueueListener, _RecentFirstQueueHandler


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
