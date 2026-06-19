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


class _FakeOwnedQuery:
    def __init__(self, session):
        self._session = session

    def delete(self):
        self._session.deleted_rows.extend(self._session.owned_rows)
        count = len(self._session.owned_rows)
        self._session.owned_rows = []
        self._session.deleted = True
        return count

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._session.owned_rows[0] if self._session.owned_rows else None


class _FakeSession:
    def __init__(self, rows=None, owned_rows=None):
        self.rows = list(rows or [])
        self.owned_rows = list(owned_rows or [])
        self.added = []
        self.deleted_rows = []
        self.deleted = False
        self.committed = False
        self.closed = False

    def query(self, *entities):
        if len(entities) == 1 and entities[0] is LibraryOwnedWork:
            return _FakeOwnedQuery(self)
        return _FakeReadQuery(self.rows)

    def add(self, row):
        self.added.append(row)
        if isinstance(row, LibraryOwnedWork) and row not in self.owned_rows:
            self.owned_rows.append(row)

    def delete(self, row):
        self.deleted_rows.append(row)
        if row in self.owned_rows:
            self.owned_rows.remove(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("本用例不应回滚")

    def close(self):
        self.closed = True


class _FakeLibraryManager:
    def has_ready_index(self):
        return True

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


class _UnavailableLibraryManager:
    def has_ready_index(self):
        return False

    def find_rj_in_ready_index(self, _rjcodes):
        raise AssertionError("ready 索引不可用时不应查询 RJ 命中")


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


def test_apply_library_index_owned_state_skips_when_ready_index_unavailable(monkeypatch):
    service = CircleCompletionService()
    item = {
        "display_rjcode": "RJ11111111",
        "linked_rjcodes": [],
        "kikoeru_found_rjcodes": [],
        "source_flags": set(),
    }

    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: _UnavailableLibraryManager())

    result = service._apply_library_index_owned_state_to_items({"RJ99999999": item})

    assert result == {
        "owned_count": 0,
        "subtitle_count": 0,
        "hit_count": 0,
        "ready_index_available": False,
    }
    assert "local_owned" not in item


def test_upsert_library_owned_rows_prunes_current_unmatched_snapshot():
    service = CircleCompletionService()
    existing = LibraryOwnedWork(
        canonical_rjcode="RJ99999999",
        owned_rjcodes=["RJ99999999"],
        primary_folder_path="/library/old",
    )
    session = _FakeSession(owned_rows=[existing])

    written = service._upsert_library_owned_rows_from_items(
        session,
        {
            "RJ99999999": {
                "local_owned": False,
                "display_rjcode": "RJ99999999",
                "linked_rjcodes": [],
                "kikoeru_found_rjcodes": [],
            }
        },
        prune_unmatched=True,
    )

    assert written == 1
    assert session.deleted_rows == [existing]
    assert session.owned_rows == []
