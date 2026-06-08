from __future__ import annotations

from app.core import circle_completion_service as circle_module
from app.core.circle_completion_service import CircleCompletionService


class _FakeWork:
    canonical_rjcode = "RJ01234567"
    linked_rjcodes = ["RJ07654321"]


class _FakeSessionRow:
    def to_dict(self):
        return {
            "id": "session-1",
            "rjcode": "RJ07654321",
            "local_download_ready": True,
            "local_download_root": "D:/downloads/RJ07654321",
            "local_downloaded_count": 7,
            "statistics": {},
            "updated_at": "2026-01-01T00:00:00",
        }


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
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
