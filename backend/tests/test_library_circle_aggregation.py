from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import routes as routes_module
from app.config.settings import AppConfig
from app.core import library_circle_aggregation_service as circle_module
from app.core.library_circle_aggregation_service import LibraryCircleAggregationService
from app.models.database import (
    LibraryIndexEntry,
)


class _NoCloseSession:
    def __init__(self, session):
        self._session = session

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._session, name)


class _FakeLibraryManager:
    def __init__(self, libraries):
        self._libraries = list(libraries)

    def _active_libraries(self):
        return list(self._libraries)

    def list_libraries(self):
        return [
            {
                "id": library.id,
                "name": library.name,
                "type": library.type,
                "path": library.path,
            }
            for library in self._libraries
        ]


def _entry(
    *,
    library_id: str,
    relative_path: str,
    rjcode: str,
    absolute_path: str = "",
    size: int = 10,
) -> LibraryIndexEntry:
    return LibraryIndexEntry(
        library_id=library_id,
        entry_type="dir",
        relative_path=relative_path,
        absolute_path=absolute_path or f"/{library_id}/{relative_path}",
        name=relative_path.rsplit("/", 1)[-1],
        name_sort_key=relative_path.rsplit("/", 1)[-1].casefold(),
        rjcode=rjcode,
        parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
        size=size,
        file_count=3,
        mtime=1000,
        depth=relative_path.count("/") + 1,
        indexed_at=1000,
    )


def _add_circle_catalog(session, *, circle_id: str, circle_name: str):
    session.execute(
        text(
            "INSERT INTO circle_catalogs (circle_id, circle_name, circle_name_normalized) "
            "VALUES (:circle_id, :circle_name, :normalized)"
        ),
        {
            "circle_id": circle_id,
            "circle_name": circle_name,
            "normalized": circle_name.casefold(),
        },
    )


def _add_circle_work(session, *, row_id: str, circle_id: str, rjcode: str, title: str = ""):
    session.execute(
        text(
            "INSERT INTO circle_works (id, circle_id, canonical_rjcode, display_rjcode, title, maker_name, linked_rjcodes) "
            "VALUES (:id, :circle_id, :rjcode, :rjcode, :title, '', NULL)"
        ),
        {
            "id": row_id,
            "circle_id": circle_id,
            "rjcode": rjcode,
            "title": title,
        },
    )


def _add_work_metadata(session, *, rjcode: str, work_name: str = "", maker_name: str = ""):
    session.execute(
        text(
            "INSERT INTO work_metadata (rjcode, work_name, maker_name) "
            "VALUES (:rjcode, :work_name, :maker_name)"
        ),
        {
            "rjcode": rjcode,
            "work_name": work_name,
            "maker_name": maker_name,
        },
    )


@pytest.fixture
def fake_library_manager(tmp_path):
    root_a = tmp_path / "lib-a"
    root_b = tmp_path / "lib-b"
    root_a.mkdir()
    root_b.mkdir()
    return _FakeLibraryManager([
        SimpleNamespace(id="local-a", name="本地 A", type="local", path=str(root_a)),
        SimpleNamespace(id="local-b", name="本地 B", type="local", path=str(root_b)),
    ])


@pytest.fixture
def circle_service(db_session, fake_library_manager, monkeypatch):
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(circle_module, "get_library_manager", lambda: fake_library_manager)
    yield LibraryCircleAggregationService()


def test_circle_aggregation_reports_conflict_locations(circle_service, db_session):
    _add_circle_catalog(db_session, circle_id="RG001", circle_name="桃色CODE")
    _add_circle_work(db_session, row_id="w1", circle_id="RG001", rjcode="RJ01000001", title="同名作品")
    db_session.add_all([
        _entry(library_id="local-a", relative_path="DLsite/RJ01000001", rjcode="RJ01000001", size=20),
        _entry(library_id="local-b", relative_path="Finished/RJ01000001", rjcode="RJ01000001", size=30),
    ])
    db_session.commit()

    groups = circle_service.list_circle_groups()
    assert groups["total"] == 1
    group = groups["items"][0]
    assert group["circle_name"] == "桃色CODE"
    assert group["work_count"] == 1
    assert group["folder_count"] == 2
    assert group["conflict_count"] == 1

    works = circle_service.list_circle_works(group["circle_key"])
    assert works["total"] == 1
    work = works["items"][0]
    assert work["rjcode"] == "RJ01000001"
    assert work["conflict"] is True
    assert len(work["locations"]) == 2
    assert {loc["library_id"] for loc in work["locations"]} == {"local-a", "local-b"}


def test_circle_aggregation_conflict_disappears_after_index_row_removed(circle_service, db_session):
    rows = [
        _entry(library_id="local-a", relative_path="DLsite/RJ01000002", rjcode="RJ01000002"),
        _entry(library_id="local-b", relative_path="Finished/RJ01000002", rjcode="RJ01000002"),
    ]
    db_session.add_all(rows)
    db_session.commit()

    group = circle_service.list_circle_groups()["items"][0]
    assert group["conflict_count"] == 1

    db_session.delete(rows[1])
    db_session.commit()

    group = circle_service.list_circle_groups()["items"][0]
    assert group["conflict_count"] == 0
    work = circle_service.list_circle_works(group["circle_key"])["items"][0]
    assert work["conflict"] is False
    assert len(work["locations"]) == 1


def test_circle_aggregation_unknown_circle_fallback(circle_service, db_session):
    db_session.add(_entry(library_id="local-a", relative_path="Other/RJ01000003", rjcode="RJ01000003"))
    db_session.commit()

    group = circle_service.list_circle_groups()["items"][0]
    assert group["circle_name"] == "未识别社团"


def test_circle_aggregation_uses_metadata_maker_name(circle_service, db_session):
    _add_work_metadata(db_session, rjcode="RJ01000004", work_name="元数据作品", maker_name="元数据社团")
    db_session.add_all([
        _entry(library_id="local-a", relative_path="Other/RJ01000004", rjcode="RJ01000004"),
    ])
    db_session.commit()

    group = circle_service.list_circle_groups()["items"][0]
    assert group["circle_name"] == "元数据社团"


def test_library_view_preferences_route_validates_mode(monkeypatch):
    saved = {}
    current = AppConfig()

    def fake_get_config():
        return current

    def fake_save_config(payload):
        saved.update(payload)
        current.ui.library.view_mode = payload["ui"]["library"]["view_mode"]
        return current

    monkeypatch.setattr(routes_module, "get_config", fake_get_config)
    monkeypatch.setattr(routes_module, "save_config", fake_save_config)

    with TestClient(routes_module.app) as client:
        assert client.get("/api/library/view-preferences").json()["view_mode"] == "directory"
        response = client.post("/api/library/view-preferences", json={"view_mode": "circle"})
        assert response.status_code == 200
        assert response.json()["view_mode"] == "circle"
        assert saved == {"ui": {"library": {"view_mode": "circle"}}}

        invalid = client.post("/api/library/view-preferences", json={"view_mode": "bad"})
        assert invalid.status_code == 400


def test_circle_group_routes_support_pagination_and_keyword(db_session, fake_library_manager, monkeypatch):
    fake_library_manager._libraries = fake_library_manager._libraries[:1]
    monkeypatch.setattr(circle_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(circle_module, "get_library_manager", lambda: fake_library_manager)
    monkeypatch.setattr(routes_module, "get_library_manager", lambda: fake_library_manager)
    monkeypatch.setattr(circle_module, "_default_service", LibraryCircleAggregationService())
    _add_circle_catalog(db_session, circle_id="RG001", circle_name="Alpha")
    _add_circle_catalog(db_session, circle_id="RG002", circle_name="Beta")
    _add_circle_work(db_session, row_id="w1", circle_id="RG001", rjcode="RJ02000001", title="Alpha Work")
    _add_circle_work(db_session, row_id="w2", circle_id="RG002", rjcode="RJ02000002", title="Beta Work")
    db_session.add_all([
        _entry(library_id="local-a", relative_path="A/RJ02000001", rjcode="RJ02000001"),
        _entry(library_id="local-a", relative_path="B/RJ02000002", rjcode="RJ02000002"),
    ])
    db_session.commit()

    with TestClient(routes_module.app) as client:
        response = client.get("/api/library/circle-groups", params={"keyword": "Alpha", "page": 1, "page_size": 1})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["circle_name"] == "Alpha"

        works_response = client.get(f"/api/library/circle-groups/{payload['items'][0]['circle_key']}/works", params={"keyword": "RJ02000001"})
        assert works_response.status_code == 200
        works_payload = works_response.json()
        assert works_payload["total"] == 1
        assert works_payload["items"][0]["rjcode"] == "RJ02000001"
