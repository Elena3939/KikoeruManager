from __future__ import annotations

from datetime import datetime

from app.models.database import ASMRDownloadSession
from app.core import circle_completion_service as circle_module
from app.core.circle_completion_service import CircleCompletionService


class _FakeWork:
    canonical_rjcode = "RJ01234567"
    linked_rjcodes = ["RJ07654321"]


class _FakeSessionRow:
    id = "session-1"
    rjcode = "RJ07654321"
    download_root = "D:/downloads/RJ07654321"
    local_downloaded_count = 7
    updated_at = datetime(2026, 1, 1)


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def distinct(self, *args, **kwargs):
        return self

    def all(self):
        return [_FakeSessionRow()]


class _FakeDb:
    def query(self, *args, **kwargs):
        return _FakeQuery()

    def commit(self):
        raise AssertionError("详情读路径不应该提交事务")

    def rollback(self):
        raise AssertionError("详情读路径不应该回滚事务")


def test_local_download_session_map_is_readonly_and_does_not_touch_disk(monkeypatch):
    service = CircleCompletionService.__new__(CircleCompletionService)

    def fail_isdir(path):
        raise AssertionError(f"详情读路径不应该访问磁盘: {path}")

    monkeypatch.setattr(circle_module.os.path, "isdir", fail_isdir)

    result = service._build_local_download_session_map(
        _FakeDb(),
        [_FakeWork()],
        {"RJ01234567": {"RJ07654321": {"link_type": "translation", "lang": "CHI_HANS"}}},
    )

    assert result["RJ01234567"]["session_id"] == "session-1"
    assert result["RJ01234567"]["download_root"] == "D:/downloads/RJ07654321"
    assert result["RJ01234567"]["downloaded_count"] == 7


def test_local_download_session_map_selects_latest_valid_record(db_session):
    db_session.add_all([
        ASMRDownloadSession(id="old", rjcode="RJ07654321", local_download_ready=True,
                            statistics={"download_root": " D:/old "}, updated_at=datetime(2026, 1, 1)),
        ASMRDownloadSession(id="blank", rjcode="RJ07654321", local_download_ready=True,
                            local_download_root="  ", statistics={"download_root": "D:/ignored"},
                            updated_at=datetime(2026, 1, 2)),
        ASMRDownloadSession(id="unfinished", rjcode="RJ07654321", local_download_ready=False,
                            local_download_root="D:/unfinished", updated_at=datetime(2026, 1, 3)),
    ])
    db_session.flush()
    service = CircleCompletionService.__new__(CircleCompletionService)
    result = service._build_local_download_session_map(db_session, [_FakeWork()], {})
    assert result["RJ01234567"]["session_id"] == "old"
    assert result["RJ01234567"]["download_root"] == "D:/old"
