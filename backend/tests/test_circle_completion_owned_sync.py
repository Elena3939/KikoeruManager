from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import circle_completion_service as circle_module
from app.core import activity_log_service as activity_log_module
from app.core import library_manager as library_manager_module
from app.core.circle_completion_service import CircleCompletionService
from app.core.task_engine import TaskEngine
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
            is_bonus_work=False,
        ),
        SimpleNamespace(
            canonical_rjcode="RJ33333333",
            display_rjcode="RJ33333333",
            linked_rjcodes=["RJ11111111", "RJ33333333"],
            is_bonus_work=True,
        ),
    ])
    write_session = _FakeSession()
    sessions = iter([read_session, write_session])

    monkeypatch.setattr(circle_module, "SessionLocal", lambda: next(sessions))
    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: _FakeLibraryManager())
    monkeypatch.setattr(
        service,
        "_load_bonus_rjcodes_for_owned_state",
        lambda _rjcodes: {"RJ33333333"},
    )

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
    assert "RJ33333333" not in added_by_canonical
    assert added_by_canonical["RJ99999999"].owned_rjcodes == ["RJ11111111"]
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
    assert row.owned_rjcodes == ["RJ11111111"]
    assert row.primary_folder_path == "/library/シルトクレーテ/[RJ11111111]"
    assert row.folder_count == 1
    assert row.folder_size == 1024
    assert row.file_count == 12
    assert row.owned_paths == ["/library/シルトクレーテ/[RJ11111111]"]
    assert row.has_local_subtitles is True
    assert row.subtitle_file_count == 3


def test_inventory_translation_search_relation_only_expands_same_language_group(monkeypatch):
    service = CircleCompletionService()
    canonical = "RJ01700001"
    simplified_query = "RJ01700002"
    simplified_owned = "RJ01700003"
    traditional = "RJ01700004"
    link_rows = [
        SimpleNamespace(canonical_rjcode=canonical, linked_rjcode=canonical, link_type="original", lang="JPN"),
        SimpleNamespace(canonical_rjcode=canonical, linked_rjcode=simplified_query, link_type="translation", lang="CHI_HANS"),
        SimpleNamespace(canonical_rjcode=canonical, linked_rjcode=simplified_owned, link_type="translation", lang="CHI_SIMP"),
        SimpleNamespace(canonical_rjcode=canonical, linked_rjcode=traditional, link_type="translation", lang="CHI_HANT"),
    ]
    owned_path = f"/library/翻译社团/[翻译社团][{simplified_owned}]"
    owned_row = SimpleNamespace(
        canonical_rjcode=canonical,
        owned_rjcodes=[canonical, simplified_query, simplified_owned, traditional],
        primary_folder_path=owned_path,
        library_id="default-local",
        owned_paths=[owned_path],
    )
    query_results = iter([[link_rows[1]], link_rows, [owned_row]])

    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return next(query_results)

    class Session:
        def query(self, *_args, **_kwargs):
            return Query()

        def close(self):
            pass

    monkeypatch.setattr(circle_module, "SessionLocal", lambda: Session())

    relation = service.get_inventory_translation_search_relation(simplified_query)

    assert relation["group_key"] == "simplified"
    assert relation["group_label"] == "简中"
    assert relation["search_rjcodes"] == [simplified_query, simplified_owned]
    assert traditional not in relation["search_rjcodes"]
    assert relation["owned_locations"] == [{
        "library_id": "default-local",
        "path": owned_path,
        "actual_rjcode": simplified_owned,
    }]


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


def test_apply_library_index_owned_state_does_not_inherit_bonus_from_translation(monkeypatch):
    service = CircleCompletionService()
    parent_code = "RJ01569979"
    bonus_code = "RJ01589264"
    translated_code = "RJ01591904"
    linked_codes = [parent_code, bonus_code, translated_code]
    parent_item = {
        "display_rjcode": parent_code,
        "linked_rjcodes": linked_codes,
        "kikoeru_found_rjcodes": [],
        "source_flags": set(),
        "is_bonus_work": False,
    }
    bonus_item = {
        "display_rjcode": bonus_code,
        "asmr_available_rjcode": translated_code,
        "linked_rjcodes": linked_codes,
        "kikoeru_found_rjcodes": [],
        "source_flags": set(),
        "is_bonus_work": True,
    }

    class LibraryManager:
        def has_ready_index(self):
            return True

        def find_rj_in_ready_index(self, rjcodes):
            return {
                translated_code: [{
                    "matched_rjcode": translated_code,
                    "rjcode": translated_code,
                    "path": f"/library/RG62878/[RG62878][{translated_code}]",
                    "library_id": "local-main",
                    "size": 1024,
                    "file_count": 8,
                }]
            } if translated_code in set(rjcodes) else {}

    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: LibraryManager())
    monkeypatch.setattr(
        service,
        "_load_bonus_rjcodes_for_owned_state",
        lambda _rjcodes: {bonus_code},
        raising=False,
    )

    result = service._apply_library_index_owned_state_to_items({
        parent_code: parent_item,
        bonus_code: bonus_item,
    })

    assert result["owned_count"] == 1
    assert parent_item["local_owned"] is True
    assert parent_item["kikoeru_found_rjcodes"] == [translated_code]
    assert bonus_item["local_owned"] is False
    assert bonus_item["kikoeru_found_rjcodes"] == []


def test_incremental_owned_sync_keeps_bonus_and_parent_targets_separate():
    service = CircleCompletionService()
    parent = SimpleNamespace(
        canonical_rjcode="RJ01569979",
        display_rjcode="RJ01591904",
        is_bonus_work=False,
    )
    bonus = SimpleNamespace(
        canonical_rjcode="RJ01589264",
        display_rjcode="RJ01589264",
        is_bonus_work=True,
    )
    bonus_codes = {"RJ01589264"}

    assert service._owned_sync_row_target_canonical(
        parent,
        "RJ01591904",
        False,
        bonus_codes,
    ) == "RJ01569979"
    assert service._owned_sync_row_target_canonical(
        bonus,
        "RJ01591904",
        False,
        bonus_codes,
    ) == ""
    assert service._owned_sync_row_target_canonical(
        parent,
        "RJ01589264",
        True,
        bonus_codes,
    ) == ""
    assert service._owned_sync_row_target_canonical(
        bonus,
        "RJ01589264",
        True,
        bonus_codes,
    ) == "RJ01589264"


@pytest.mark.asyncio
async def test_refresh_circle_owned_state_uses_one_local_index_batch(monkeypatch):
    service = CircleCompletionService()
    circle_id = "RG_OWNED_FAST"
    catalog = SimpleNamespace(circle_id=circle_id, circle_name="本地拥有态测试社团")
    rows = [
        SimpleNamespace(
            circle_id=circle_id,
            canonical_rjcode="RJ01000001",
            display_rjcode="RJ01000001",
            title="新增拥有",
            source_mask="dlsite",
            linked_rjcodes=["RJ01000001"],
            has_kikoeru=False,
            kikoeru_found_rjcodes=[],
            kikoeru_subtitle_rjcodes=[],
            has_dlsite=True,
            has_asmr_one=False,
            asmr_available_rjcode=None,
            updated_at=None,
        ),
        SimpleNamespace(
            circle_id=circle_id,
            canonical_rjcode="RJ01000002",
            display_rjcode="RJ01000002",
            title="取消拥有",
            source_mask="dlsite,kikoeru",
            linked_rjcodes=["RJ01000002"],
            has_kikoeru=True,
            kikoeru_found_rjcodes=["RJ01000002"],
            kikoeru_subtitle_rjcodes=["RJ01000002"],
            has_dlsite=True,
            has_asmr_one=False,
            asmr_available_rjcode=None,
            updated_at=None,
        ),
    ]

    class Query:
        def __init__(self, *, first_value=None, all_values=None):
            self.first_value = first_value
            self.all_values = list(all_values or [])

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return self.first_value

        def all(self):
            return list(self.all_values)

    class ReadSession:
        def __init__(self):
            self.query_count = 0

        def query(self, *_entities):
            self.query_count += 1
            if self.query_count == 1:
                return Query(first_value=catalog)
            return Query(all_values=rows)

        def expunge_all(self):
            pass

        def close(self):
            pass

    class WriteSession:
        def __init__(self):
            self.merged = []
            self.committed = False

        def merge(self, row):
            self.merged.append(row)

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("本用例不应回滚")

        def close(self):
            pass

    read_session = ReadSession()
    write_session = WriteSession()
    sessions = iter([read_session, write_session])

    monkeypatch.setattr(circle_module, "SessionLocal", lambda: next(sessions))
    monkeypatch.setattr(activity_log_module, "log_circle_completion_event", lambda *_args, **_kwargs: None)
    index_batches = []
    owned_writes = []

    def fake_apply(items_by_canonical):
        index_batches.append(set(items_by_canonical))
        gained = items_by_canonical["RJ01000001"]
        gained.update({
            "has_kikoeru": True,
            "kikoeru_found_rjcodes": ["RJ01000001"],
            "kikoeru_subtitle_rjcodes": [],
            "local_owned": True,
            "local_subtitle_present": False,
            "local_folder_size": 1024,
            "local_file_count": 4,
            "subtitle_file_count": 0,
            "subtitle_dir": "",
            "owned_paths": ["/library/RJ01000001"],
            "primary_library_id": "local-main",
        })
        lost = items_by_canonical["RJ01000002"]
        lost.update({
            "has_kikoeru": False,
            "kikoeru_found_rjcodes": [],
            "kikoeru_subtitle_rjcodes": [],
            "local_owned": False,
            "local_subtitle_present": False,
            "local_folder_size": 0,
            "local_file_count": 0,
            "subtitle_file_count": 0,
            "subtitle_dir": "",
            "owned_paths": [],
            "primary_library_id": "",
        })
        return {
            "owned_count": 1,
            "subtitle_count": 0,
            "hit_count": 1,
            "ready_index_available": True,
        }

    monkeypatch.setattr(service, "_apply_library_index_owned_state_to_items", fake_apply)
    monkeypatch.setattr(
        service,
        "_upsert_library_owned_rows_from_items",
        lambda _db, items, **kwargs: owned_writes.append((set(items), kwargs)) or len(items),
    )
    progress = []

    result = await service.refresh_circle_owned_state(
        circle_id,
        ["RJ01000001", "RJ01000002"],
        progress_callback=lambda value, step, **_meta: progress.append((value, step)),
    )

    assert index_batches == [{"RJ01000001", "RJ01000002"}]
    assert result["refreshed_count"] == 2
    assert result["changed_count"] == 2
    assert result["kikoeru_owned_count"] == 1
    assert result["owned_only"] is True
    assert progress[-1] == (100, "本地拥有状态刷新完成")
    assert owned_writes == [(
        {"RJ01000001", "RJ01000002"},
        {"prune_unmatched": True},
    )]
    assert write_session.committed is True
    rows_by_code = {row.canonical_rjcode: row for row in rows}
    assert rows_by_code["RJ01000001"].has_kikoeru is True
    assert rows_by_code["RJ01000001"].kikoeru_found_rjcodes == ["RJ01000001"]
    assert rows_by_code["RJ01000002"].has_kikoeru is False
    assert rows_by_code["RJ01000002"].kikoeru_found_rjcodes == []
    assert rows_by_code["RJ01000002"].source_mask == "dlsite"


@pytest.mark.asyncio
async def test_owned_only_task_skips_full_remote_refresh(monkeypatch):
    calls = []

    class Service:
        async def refresh_circle_owned_state(self, circle_id, codes, **kwargs):
            calls.append(("owned", circle_id, list(codes), kwargs))
            return {
                "circle_id": circle_id,
                "circle_name": "本地拥有态测试社团",
                "refreshed_count": len(codes),
                "changed_count": 1,
                "kikoeru_owned_count": 1,
                "owned_only": True,
                "items": [],
            }

        async def refresh_circle_works(self, *_args, **_kwargs):
            raise AssertionError("只刷新拥有态时不应进入远程状态刷新")

    class Task:
        def __init__(self):
            self.progress = 0
            self.current_step = ""
            self.task_metadata = {
                "circle_id": "RG_OWNED_FAST",
                "circle_name": "本地拥有态测试社团",
                "canonical_rjcodes": ["RJ01000001"],
                "owned_only": True,
                "progress_log": [],
            }

        def update_progress(self, progress, step):
            self.progress = progress
            self.current_step = step

        def is_cancelled(self):
            return False

    monkeypatch.setattr(circle_module, "get_circle_completion_service", lambda: Service())
    task = Task()

    await TaskEngine._process_circle_completion_refresh_selected(SimpleNamespace(), task)

    assert len(calls) == 1
    assert calls[0][:3] == ("owned", "RG_OWNED_FAST", ["RJ01000001"])
    assert task.progress == 100
    assert task.current_step == "本地拥有状态刷新完成"
    assert task.task_metadata["owned_only"] is True
    assert task.task_metadata["refreshed_count"] == 1


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
