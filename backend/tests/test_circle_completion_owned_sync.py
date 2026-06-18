from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import circle_completion_service as circle_module
from app.core import library_manager as library_manager_module
from app.core.circle_completion_service import CircleCompletionService
from app.models.database import LibraryOwnedWork


class _FakeReadQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDeleteQuery:
    def __init__(self, session):
        self._session = session

    def delete(self):
        self._session.deleted = True
        return 0

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.deleted = False
        self.committed = False
        self.closed = False

    def query(self, *entities):
        if len(entities) == 1 and entities[0] is LibraryOwnedWork:
            return _FakeDeleteQuery(self)
        return _FakeReadQuery(self.rows)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("本用例不应回滚")

    def close(self):
        self.closed = True


class _FakeLibraryManager:
    def find_rj_in_ready_index(self, rjcodes):
        assert "RJ11111111" in set(rjcodes)
        return {
            "RJ11111111": [
                {
                    "path": "/library/RaRo/[RaRo][RJ11111111]",
                    "library_id": "local-main",
                    "size": 123,
                    "file_count": 4,
                }
            ]
        }


@pytest.mark.asyncio
async def test_sync_local_owned_index_writes_related_circle_work_canonical(monkeypatch):
    service = CircleCompletionService()
    read_session = _FakeSession([
        SimpleNamespace(
            canonical_rjcode="RJ99999999",
            display_rjcode="RJ99999999",
            linked_rjcodes=["RJ11111111"],
        )
    ])
    write_session = _FakeSession()
    sessions = iter([read_session, write_session])

    monkeypatch.setattr(circle_module, "SessionLocal", lambda: next(sessions))
    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: _FakeLibraryManager())

    async def fake_resolve_canonical(rjcode):
        assert rjcode == "RJ11111111"
        return {
            "canonical_rjcode": "RJ22222222",
            "linked_rjcodes": ["RJ11111111", "RJ22222222"],
        }

    monkeypatch.setattr(service, "resolve_canonical_rj", fake_resolve_canonical)

    result = await service.sync_local_owned_index()

    added_by_canonical = {row.canonical_rjcode: row for row in write_session.added}
    assert result["owned_count"] == 2
    assert set(added_by_canonical) == {"RJ22222222", "RJ99999999"}
    assert set(added_by_canonical["RJ99999999"].owned_rjcodes) == {
        "RJ11111111",
        "RJ22222222",
        "RJ99999999",
    }
    assert added_by_canonical["RJ99999999"].owned_paths == ["/library/RaRo/[RaRo][RJ11111111]"]
    assert write_session.deleted is True
    assert write_session.committed is True


def test_upsert_library_owned_rows_from_current_index_items():
    service = CircleCompletionService()
    session = _FakeSession()

    written = service._upsert_library_owned_rows_from_items(
        session,
        {
            "RJ99999999": {
                "local_owned": True,
                "display_rjcode": "RJ22222222",
                "linked_rjcodes": ["RJ11111111", "RJ22222222"],
                "kikoeru_found_rjcodes": ["RJ11111111"],
                "owned_paths": ["/library/シルトクレーテ/[RJ11111111]"],
                "local_folder_size": 1024,
                "local_file_count": 12,
                "local_subtitle_present": True,
                "subtitle_file_count": 3,
                "subtitle_dir": "/library/シルトクレーテ/[RJ11111111]/subtitles",
            }
        },
    )

    assert written == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.canonical_rjcode == "RJ99999999"
    assert set(row.owned_rjcodes) == {"RJ11111111", "RJ22222222", "RJ99999999"}
    assert row.primary_folder_path == "/library/シルトクレーテ/[RJ11111111]"
    assert row.folder_count == 1
    assert row.folder_size == 1024
    assert row.file_count == 12
    assert row.owned_paths == ["/library/シルトクレーテ/[RJ11111111]"]
    assert row.has_local_subtitles is True
    assert row.subtitle_file_count == 3
