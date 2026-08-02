from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.notification_helper import build_notification_extra_for_task
from app.core.failure_reason_formatter import format_extract_failure_message
from app.core import task_notification_service
from app.core.task_engine import TaskStatus, TaskType
from app.models.database import NotificationInboxItem, NotificationOutbox


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **_kw):
    return "JSON"


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    NotificationInboxItem.__table__.create(bind=engine)
    NotificationOutbox.__table__.create(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _inbox(item_id: str, *, created_at: datetime, is_read: bool = True) -> NotificationInboxItem:
    return NotificationInboxItem(
        id=item_id,
        event_key=f"event:{item_id}",
        event_type="completed",
        severity="info",
        group_key=item_id,
        group_type="task",
        primary_task_id=f"task:{item_id}",
        task_ids=[f"task:{item_id}"],
        title=f"通知 {item_id}",
        summary=f"通知摘要 {item_id}",
        is_read=is_read,
        created_at=created_at,
        updated_at=created_at,
    )


def _outbox(item_id: str, inbox_item_id: str, *, status: str, created_at: datetime) -> NotificationOutbox:
    return NotificationOutbox(
        id=item_id,
        inbox_item_id=inbox_item_id,
        event_key=f"event:{inbox_item_id}",
        channel="email",
        status=status,
        payload={"subject": item_id},
        created_at=created_at,
    )


def test_cleanup_old_notifications_prunes_terminal_outbox_and_keeps_pending(monkeypatch):
    TestingSessionLocal = _session_factory()
    monkeypatch.setattr("app.models.database.SessionLocal", TestingSessionLocal)

    old = datetime.now() - timedelta(days=45)
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                _inbox("old-sent", created_at=old),
                _inbox("old-pending", created_at=old),
                _outbox("outbox-sent", "old-sent", status="sent", created_at=old),
                _outbox("outbox-pending", "old-pending", status="pending", created_at=old),
                _outbox("orphan-failed", "missing", status="failed", created_at=old),
            ]
        )
        db.commit()
    finally:
        db.close()

    deleted = task_notification_service.cleanup_old_notifications(retain_days=30, max_items=200)

    db = TestingSessionLocal()
    try:
        inbox_ids = {row.id for row in db.query(NotificationInboxItem).all()}
        outbox = {row.id: row.status for row in db.query(NotificationOutbox).all()}
    finally:
        db.close()

    assert deleted == 2
    assert inbox_ids == {"old-pending"}
    assert outbox == {"outbox-pending": "pending"}


def test_cleanup_old_notifications_caps_terminal_outbox_without_touching_active(monkeypatch):
    TestingSessionLocal = _session_factory()
    monkeypatch.setattr("app.models.database.SessionLocal", TestingSessionLocal)

    now = datetime.now()
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                _outbox("sent-1", "inbox-1", status="sent", created_at=now - timedelta(minutes=3)),
                _outbox("sent-2", "inbox-2", status="sent", created_at=now - timedelta(minutes=2)),
                _outbox("failed-3", "inbox-3", status="failed", created_at=now - timedelta(minutes=1)),
                _outbox("pending-4", "inbox-4", status="pending", created_at=now - timedelta(minutes=4)),
            ]
        )
        db.commit()
    finally:
        db.close()

    deleted = task_notification_service.cleanup_old_notifications(
        retain_days=365,
        max_items=200,
        outbox_max_items=2,
    )

    db = TestingSessionLocal()
    try:
        outbox = {row.id: row.status for row in db.query(NotificationOutbox).all()}
    finally:
        db.close()

    assert deleted == 1
    assert outbox == {
        "sent-2": "sent",
        "failed-3": "failed",
        "pending-4": "pending",
    }


def test_baidu_netdisk_download_notification_uses_download_payload():
    now = datetime.now()
    task = SimpleNamespace(
        id="task-baidu",
        type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        status=TaskStatus.COMPLETED,
        started_at=now - timedelta(seconds=9),
        completed_at=now,
        current_step="百度网盘下载完成",
        rjcode="RJ01632896",
        task_metadata={
            "task_domain": "baidu_netdisk",
            "task_kind": TaskType.BAIDU_NETDISK_DOWNLOAD.value,
            "source_label": "百度网盘",
            "download_files": [
                {
                    "name": "RJ01632896.z1p",
                    "relative_path": "RJ01632896.z1p",
                    "size": 1024,
                    "status": "completed",
                    "downloaded": 1024,
                }
            ],
            "download_runtime": {
                "total_files": 1,
                "completed_files": 1,
                "total_bytes": 1024,
            },
            "progress_log": [
                {"time": "22:44:40", "message": "百度网盘下载完成", "level": "info"},
            ],
        },
    )

    payload = build_notification_extra_for_task(task)

    assert payload["stats"]["total_files"] == 1
    assert payload["stats"]["downloaded"] == 1
    assert payload["stats"]["total_size"] == "1.0 KB"
    assert payload["stats"]["duration"]
    assert "RJ01632896.z1p" in str(payload["download_files"])
    assert payload["download_work_cards"][0]["rjcode"] == "RJ01632896"


def test_baidu_netdisk_partial_success_is_failed_event():
    task = SimpleNamespace(
        type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        task_metadata={
            "task_domain": "baidu_netdisk",
            "download_files": [
                {"name": "ok.zip", "status": "completed"},
                {"name": "bad.zip", "status": "failed"},
            ],
            "failed_files": [{"name": "bad.zip", "failure_reason": "下载失败"}],
        },
    )

    assert task_notification_service._is_download_partial_success(task) is True


def test_asmr_enhanced_partial_success_is_failed_event():
    task = SimpleNamespace(
        id="asmr-partial",
        type=SimpleNamespace(value="asmr_sync_download"),
        status=SimpleNamespace(value="completed"),
        task_metadata={
            "download_mode": "enhanced",
            "failed_files": [{"relative_path": "audio/02.wav", "reason": "断流"}],
            "performance_metrics": {"success_count": 1, "failed_count": 1},
        },
    )

    assert task_notification_service._is_download_partial_success(task) is True
    assert task_notification_service._final_event_type("asmr-partial", "task", task) == "failed"


def test_notification_business_key_column_allows_long_keys():
    assert isinstance(NotificationInboxItem.__table__.c.business_key.type, Text)


def test_extract_failure_formatter_uses_specific_reason_codes():
    assert "密码未命中" in format_extract_failure_message({"extract_failure_reason": "wrong_password"})
    assert "磁盘空间不足" in format_extract_failure_message({"extract_failure_reason": "disk_full"})
    assert "压缩包损坏" in format_extract_failure_message({"extract_failure_reason": "archive_corrupt"})
    assert "不支持该压缩方法" in format_extract_failure_message({"extract_failure_reason": "unsupported_method"})
    assert "文件名疑似乱码" in format_extract_failure_message({
        "extract_failure_reason": "garbled_filename",
        "garbled_filename_sample": "偭偪.wav",
    })


def test_problem_work_notification_extra_uses_specific_extract_reason():
    task = SimpleNamespace(
        id="task-extract-corrupt",
        type=TaskType.AUTO_PROCESS,
        status=TaskStatus.WAITING_MANUAL,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        current_step="解压失败，已加入问题作品列表",
        error_message="解压失败：无正确密码",
        rjcode="RJ09999999",
        task_metadata={
            "task_domain": "import",
            "task_kind": TaskType.AUTO_PROCESS.value,
            "failure_stage": "extract",
            "extract_failure_reason": "archive_corrupt",
            "rjcode": "RJ09999999",
        },
    )

    payload = build_notification_extra_for_task(task)

    assert payload["rj_work_cards"][0]["changes"][0]["text"] == "解压失败：压缩包损坏或下载不完整（Headers/Data Error）"


def test_waiting_manual_notification_summary_appends_specific_reason():
    task = SimpleNamespace(
        id="task-extract-volume",
        type=TaskType.AUTO_PROCESS,
        status=TaskStatus.WAITING_MANUAL,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        current_step="解压失败，已加入问题作品列表",
        error_message="解压失败：无正确密码",
        rjcode="RJ08888888",
        source_path="/down/RJ08888888.zip",
        output_path="",
        progress=100,
        task_metadata={
            "task_domain": "import",
            "task_kind": TaskType.AUTO_PROCESS.value,
            "failure_stage": "extract",
            "extract_failure_reason": "volume_incomplete",
            "rjcode": "RJ08888888",
        },
    )

    info = task_notification_service._build_notification_info(
        "waiting_manual",
        "task-extract-volume",
        "task",
        task,
    )

    assert "等待处理" in info["summary"]
    assert "分卷压缩包不完整" in info["summary"]
