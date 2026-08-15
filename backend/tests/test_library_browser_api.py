import asyncio
import json
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import routes as routes_module
from app.config.settings import LibraryConfigItem, StorageConfig
from app.core import library_index as library_index_module
from app.core import library_folder_completion_service as folder_completion_module
from app.core import library_manager as library_manager_module
from app.core import redis_service as redis_service_module
from app.core.metadata_service import MetadataService
from app.core.library_index.types import IndexEntry


class _RuntimeConfig:
    """让 ``get_config().storage`` 返回真实的 StorageConfig（带多库存条目）。

    生产 ``load_library_config()`` 直接调 ``get_config().storage.model_dump()``，
    完全不读 yaml；原测试 monkeypatch 的 ``_config_file_path`` 路径根本未被使用。
    本测试改为直接构造一份多库存 StorageConfig，覆盖 get_config 即可。
    """

    def __init__(self, storage: StorageConfig):
        self.storage = storage


class _FakeJsonRequest:
    def __init__(self, payload, *, headers=None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload


def test_library_manager_create_folder_targets_current_directory(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    current_dir = library_root / "circle" / "RJ00000001"
    current_dir.mkdir(parents=True)
    library = library_manager_module.LibraryDefinition(
        id="local-create",
        name="本地创建测试",
        type="local",
        path=str(library_root),
    )
    manager = object.__new__(library_manager_module.LibraryManager)
    index_targets = []
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_invalidate_local_browse_caches", lambda *_args: None)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args: None)
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_upsert_subtree",
        lambda _library, path: index_targets.append(path),
    )

    result = asyncio.run(manager.create_folder("local-create", str(current_dir), "自定义目录"))

    created_path = current_dir / "自定义目录"
    assert result["path"] == str(created_path)
    assert created_path.is_dir()
    assert index_targets == [str(created_path)]

    with pytest.raises(FileExistsError, match="同名"):
        asyncio.run(manager.create_folder("local-create", str(current_dir), "自定义目录"))
    with pytest.raises(ValueError, match="非法路径字符"):
        manager.resolve_create_folder_target("local-create", str(current_dir), "../越界目录")
    assert not (library_root / "越界目录").exists()


def test_find_rj_in_ready_index_uses_usable_snapshot_while_catching_up(monkeypatch):
    library = library_manager_module.LibraryDefinition(
        id="local-catching-up",
        name="追赶中库存",
        type="local",
        path="D:/library",
    )
    entry = IndexEntry(
        library_id=library.id,
        entry_type="dir",
        relative_path="社团/RJ01618558",
        absolute_path="D:/library/社团/RJ01618558",
        name="RJ01618558",
        rjcode="RJ01618558",
        file_count=30,
        materialized_seq=287,
    )

    class _IndexService:
        def __init__(self):
            self.find_calls = []

        def is_ready(self, _library_id):
            return False

        def has_usable_snapshot(self, _library_id):
            return True

        def find_by_rjcode(self, *_args, **_kwargs):
            self.find_calls.append((_args, _kwargs))
            return [entry]

    manager = object.__new__(library_manager_module.LibraryManager)
    manager._active_libraries = lambda: [library]
    index_service = _IndexService()
    monkeypatch.setattr(
        library_index_module,
        "get_library_index_service",
        lambda: index_service,
    )

    result = manager.find_rj_in_ready_index(
        "RJ01618558",
        include_subtitle_state=False,
    )

    assert result["RJ01618558"][0]["path"] == entry.absolute_path
    assert result["RJ01618558"][0]["file_count"] == 30
    assert index_service.find_calls[0][1]["repair_missing"] is False
    assert manager.has_ready_index() is True


def test_legacy_library_mutations_invalidate_subtitle_folder_summary_cache(monkeypatch):
    library = SimpleNamespace(id="library-a")
    invalidated = []

    class _Manager:
        def get_library_definition(self, library_id):
            return library if library_id == library.id else None

        def find_local_library_for_path(self, _path):
            return library

        async def rename(self, _library_id, old_path, new_name):
            return {"new_path": f"{old_path}-{new_name}"}

        async def delete(self, _library_id, _path, *, confirmed=False):
            return {"deleted": bool(confirmed)}

        async def batch_delete(self, _library_id, paths, *, confirmed=False):
            return {
                "success_count": len(paths) if confirmed else 0,
                "failed_paths": [],
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: _Manager())
    monkeypatch.setattr(
        routes_module,
        "_invalidate_rj_subtitle_folder_summary_cache",
        lambda library_id: invalidated.append(library_id),
    )

    asyncio.run(routes_module.rename_library_file(_FakeJsonRequest({
        "path": "D:/library/RJ00000001",
        "new_name": "RJ00000001 renamed",
        "library_id": library.id,
    })))
    asyncio.run(routes_module.delete_library_file(_FakeJsonRequest({
        "path": "D:/library/RJ00000001",
        "confirmed": True,
        "library_id": library.id,
    })))
    asyncio.run(routes_module.batch_delete_library_items(_FakeJsonRequest({
        "paths": ["D:/library/RJ00000001", "D:/library/RJ00000002"],
        "confirmed": True,
        "library_id": library.id,
    })))

    assert invalidated == [library.id, library.id, library.id]


def test_legacy_folder_contents_keeps_non_library_realtime_io(monkeypatch, tmp_path):
    source_dir = tmp_path / "incoming"
    nested_dir = source_dir / "nested"
    nested_dir.mkdir(parents=True)
    (source_dir / "track.wav").write_bytes(b"audio")
    (nested_dir / "subtitle.vtt").write_text("WEBVTT", encoding="utf-8")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "find_local_library_for_path", lambda _path: None)
    monkeypatch.setattr(routes_module, "get_library_manager", lambda: manager)

    result = asyncio.run(
        routes_module.get_library_folder_contents(
            _FakeJsonRequest({"path": str(source_dir), "prefer_index": True})
        )
    )

    assert result["browse_via_index"] is False
    assert result["total_files"] == 2
    assert [item["relative_path"] for item in result["items"]] == [
        "nested/subtitle.vtt",
        "track.wav",
    ]

    shallow_result = asyncio.run(
        routes_module.get_library_folder_contents(
            _FakeJsonRequest({"path": str(source_dir), "recursive": False, "prefer_index": True})
        )
    )

    assert shallow_result["browse_via_index"] is False
    assert shallow_result["total_files"] == 1
    assert [item["name"] for item in shallow_result["items"]] == ["nested", "track.wav"]


def test_library_browser_endpoints_support_multi_library(client, monkeypatch, tmp_path):
    local_root = tmp_path / "library-a"
    # ``/api/library/browser/files`` 默认列 library root 的直接子项；要让作品在第一层
    # 被命中，目标作品目录就放在 library 根下，不要再多套一层（原测试套了两层导致
    # 接口只返回 "RJ000001"，断言 "[RJ000001] Demo" 永远 false）。
    target_dir = local_root / "[RJ000001] Demo"
    target_dir.mkdir(parents=True)
    (target_dir / "track.wav").write_bytes(b"demo-data")

    storage = StorageConfig(
        library_path=str(local_root),
        libraries=[
            LibraryConfigItem(
                id="local-a",
                name="本地 A",
                type="local",
                path=str(local_root),
                enabled=True,
            )
        ],
        default_library_id="local-a",
        default_extract_library_id="local-a",
        health_warning_free_gb=1,
        stats_cache_ttl_seconds=1,
    )
    runtime_cfg = _RuntimeConfig(storage)
    monkeypatch.setattr(library_manager_module, "get_config", lambda: runtime_cfg)

    list_response = client.get("/api/library/libraries")
    assert list_response.status_code == 200
    libraries = list_response.json()["libraries"]
    assert libraries[0]["id"] == "local-a"

    browse_response = client.get("/api/library/browser/files", params={"library_id": "local-a", "page": 1, "page_size": 50})
    assert browse_response.status_code == 200
    payload = browse_response.json()
    assert payload["total"] == 1
    assert payload["files"][0]["name"] == "[RJ000001] Demo"

    folder_response = client.post(
        "/api/library/browser/folder-contents",
        json={"library_id": "local-a", "path": str(target_dir)},
    )
    assert folder_response.status_code == 200
    assert folder_response.json()["total_files"] == 1

    summary_response = client.post(
        "/api/library/browser/compute-folder-sizes",
        json={"library_id": "local-a", "paths": [str(target_dir)], "include_counts": True},
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()["results"][0]
    assert summary["success"] is True
    assert summary["file_count"] == 0
    assert summary["folder_count"] == 0
    assert summary["size_status"] == "pending"
    assert summary["index_refresh_pending"] is True

    stats_response = client.get("/api/library/browser/stats", params={"force_refresh": "true"})
    assert stats_response.status_code == 200
    assert "all_libraries" in stats_response.json()

    create_response = client.post(
        "/api/library/browser/create-folder",
        headers={"Idempotency-Key": f"test-create-library-folder-{uuid.uuid4().hex}"},
        json={
            "library_id": "local-a",
            "parent_path": str(target_dir),
            "name": "自定义目录",
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["path"] == str(target_dir / "自定义目录")
    assert (target_dir / "自定义目录").is_dir()

    duplicate_response = client.post(
        "/api/library/browser/create-folder",
        headers={"Idempotency-Key": f"test-create-library-folder-duplicate-{uuid.uuid4().hex}"},
        json={
            "library_id": "local-a",
            "parent_path": str(target_dir),
            "name": "自定义目录",
        },
    )
    assert duplicate_response.status_code == 409

    invalid_name_response = client.post(
        "/api/library/browser/create-folder",
        headers={"Idempotency-Key": "test-create-library-folder-invalid"},
        json={
            "library_id": "local-a",
            "parent_path": str(target_dir),
            "name": "../越界目录",
        },
    )
    assert invalid_name_response.status_code == 400
    assert not (local_root / "越界目录").exists()


def test_library_browser_video_preview_keeps_range_response_uncompressed(client, monkeypatch, tmp_path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"\x00" * (1024 * 1024))

    library = library_manager_module.LibraryDefinition(
        id="local-preview",
        name="本地预览",
        type="local",
        path=str(tmp_path),
        enabled=True,
    )

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(routes_module, "get_library_manager", lambda: manager)

    response = client.get(
        "/api/library/browser/preview",
        params={
            "library_id": "local-preview",
            "path": str(video_path),
        },
        headers={
            "Accept-Encoding": "gzip",
            "Range": "bytes=0-99",
        },
    )

    assert response.status_code == 206
    assert response.headers.get("content-encoding") is None
    assert response.headers.get("content-range") == f"bytes 0-99/{video_path.stat().st_size}"
    assert response.headers.get("content-length") == "100"
    assert response.headers.get("accept-ranges") == "bytes"


def test_local_inventory_reads_prefer_usable_index_snapshot(monkeypatch, tmp_path):
    local_root = tmp_path / "library"
    circle_dir = local_root / "Circle"
    rj_dir = circle_dir / "RJ01000001"
    subtitle_dir = rj_dir / "subtitles"
    subtitle_dir.mkdir(parents=True)
    (rj_dir / "track.mp3").write_bytes(b"audio")
    (subtitle_dir / "track.vtt").write_bytes(b"subt")
    (circle_dir / "cover.jpg").write_bytes(b"jpg")

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(local_root),
        enabled=True,
    )

    def entry(relative_path, entry_type, size, file_count):
        return IndexEntry(
            library_id=library.id,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(local_root / Path(relative_path)),
            name=relative_path.rsplit("/", 1)[-1],
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=size,
            file_count=file_count,
            mtime=1000,
            depth=relative_path.count("/") + 1,
            indexed_at=1000,
        )

    entries = {
        item.relative_path: item
        for item in [
            entry("Circle", "dir", 12, 3),
            entry("Circle/RJ01000001", "dir", 9, 2),
            entry("Circle/RJ01000001/subtitles", "dir", 4, 1),
            entry("Circle/RJ01000001/old-track.mp3", "file", 5, 0),
            entry("Circle/RJ01000001/subtitles/track.vtt", "file", 4, 0),
            entry("Circle/cover.jpg", "file", 3, 0),
        ]
    }

    class FakeIndexService:
        def is_ready(self, library_id):
            return library_id == library.id

        def has_usable_snapshot(self, library_id):
            return library_id == library.id

        def get_entry(self, library_id, relative_path):
            return entries.get(relative_path)

        def list_children_page(self, library_id, parent_path="", **kwargs):
            sort_by = str(kwargs.get("sort_by") or "name")
            reverse = str(kwargs.get("sort_order") or "asc").lower() == "desc"
            children = [
                item
                for item in entries.values()
                if (item.parent_path or "") == (parent_path or "")
            ]
            if sort_by == "size":
                children.sort(key=lambda item: (int(item.size or 0), item.name), reverse=reverse)
            else:
                children.sort(key=lambda item: item.name.lower(), reverse=reverse)
            return {
                "entries": children,
                "total": len(children),
            }

        def list_subtree_entries(self, library_id, relative_path="", include_self=True, entry_type=None, **_kwargs):
            normalized = str(relative_path or "").strip("/")
            if not normalized:
                candidates = list(entries.values())
            else:
                candidates = [
                    item
                    for item in entries.values()
                    if (
                        item.relative_path == normalized
                        if include_self
                        else False
                    )
                    or item.relative_path.startswith(f"{normalized}/")
                ]
            if entry_type:
                candidates = [item for item in candidates if item.entry_type == entry_type]
            return sorted(
                candidates,
                key=lambda item: (item.depth, item.relative_path),
            )

        def count_descendant_dirs_many(self, library_id, relative_paths):
            return {
                relative_path: sum(
                    1
                    for item in entries.values()
                    if item.entry_type == "dir"
                    and item.relative_path.startswith(f"{relative_path}/")
                )
                for relative_path in relative_paths
            }

        def get_status(self, library_id):
            return SimpleNamespace(folder_count=2)

        def get_library_stats(self, library_id):
            return {
                "folder_count": 2,
                "total_size_bytes": sum(
                    int(item.size or 0)
                    for item in entries.values()
                    if item.entry_type == "file"
                ),
            }

        def handle_self_mutation_batch(self, library_id, *, upserts=None, deletes=None):
            result = {"upserts": 0, "deletes": 0}
            for relative_path in deletes or []:
                normalized = str(relative_path or "").strip("/")
                for key in list(entries.keys()):
                    if key == normalized or key.startswith(f"{normalized}/"):
                        entries.pop(key, None)
                        result["deletes"] += 1
            return result

    manager = object.__new__(library_manager_module.LibraryManager)
    manager._size_cache = {}
    ledger_effects = []

    class FakeMutationService:
        def prepare(self, **kwargs):
            ledger_effects.extend(kwargs["effects_by_library"][library.id])
            return SimpleNamespace(
                operation_id="inventory-read-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, _operation_id):
            return None

        def finalize(self, _operation_id, **kwargs):
            for effect in kwargs["actual_effects_by_library"].get(library.id, []):
                if effect["kind"] != "delete":
                    continue
                relative_path = effect["relative_path"]
                for key in list(entries):
                    if key == relative_path or (
                        effect["scope"] == "subtree" and key.startswith(relative_path + "/")
                    ):
                        entries.pop(key, None)
            return kwargs["actual_result"]

    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: FakeIndexService())
    monkeypatch.setattr(library_index_module, "get_library_index_mutation_service", lambda: FakeMutationService())

    list_result = manager._list_local_files(
        library,
        page=1,
        page_size=20,
        search="",
        current_path=str(rj_dir),
        sort_by="name",
        sort_order="asc",
    )
    assert list_result.get("browse_via_index") is not True
    assert [item["name"] for item in list_result["files"]] == ["subtitles", "track.mp3"]
    subtitles_item = next(item for item in list_result["files"] if item["name"] == "subtitles")
    assert subtitles_item["size"] == 4
    assert subtitles_item["size_status"] == "stale"
    assert subtitles_item["size_via_index"] is True

    def fail_disk_listing(*_args, **_kwargs):
        raise AssertionError("本地普通浏览应优先走索引，不能先扫磁盘")

    monkeypatch.setattr(manager, "_list_local_files", fail_disk_listing)
    indexed_list_result = asyncio.run(
        manager.list_files(
            library.id,
            page=1,
            page_size=20,
            current_path=str(rj_dir),
            sort_by="name",
            sort_order="asc",
        )
    )
    assert indexed_list_result["browse_via_index"] is True
    assert [item["name"] for item in indexed_list_result["files"]] == ["subtitles"]
    assert indexed_list_result["total"] == 1

    result = asyncio.run(manager.folder_contents(library.id, str(circle_dir), recursive=False))

    assert result.get("browse_via_index") is True
    assert result["total_files"] == 3
    rj_item = next(item for item in result["items"] if item["name"] == "RJ01000001")
    assert rj_item["size"] == 9
    assert rj_item["size_status"] == "stale"
    assert rj_item["index_refresh_pending"] is True
    assert rj_item["file_count"] == 2
    assert rj_item["folder_count"] == 1
    assert rj_item["folder_count_status"] == "ready"

    recursive_result = asyncio.run(manager.folder_contents(library.id, str(circle_dir), recursive=True))
    assert recursive_result.get("browse_via_index") is True
    assert recursive_result["total_files"] == 2
    assert [item["relative_path"] for item in recursive_result["items"]] == [
        "RJ01000001/subtitles/track.vtt",
        "cover.jpg",
    ]

    indexed_summary = manager.folder_size_summary_via_index(library, str(rj_dir), include_counts=True)
    assert indexed_summary["browse_via_index"] is True
    assert indexed_summary["size"] == 9
    assert indexed_summary["size_status"] == "stale"
    assert indexed_summary["file_count"] == 2
    assert indexed_summary["folder_count"] is None
    assert indexed_summary["count_status"] == "lazy"

    shallow_realtime_result = asyncio.run(
        manager.folder_contents(library.id, str(circle_dir), recursive=False, prefer_index=False)
    )
    assert shallow_realtime_result.get("browse_via_index") is not True
    assert shallow_realtime_result["total_files"] == 1
    assert [item["name"] for item in shallow_realtime_result["items"]] == ["RJ01000001", "cover.jpg"]
    shallow_rj_item = next(item for item in shallow_realtime_result["items"] if item["name"] == "RJ01000001")
    assert shallow_rj_item["size_status"] == "stale"
    assert shallow_rj_item["file_count"] == 2
    assert shallow_rj_item["folder_count"] is None
    assert shallow_rj_item["folder_count_status"] == "lazy"

    folders_payload = asyncio.run(manager.list_local_folders_only(library.id, str(circle_dir), include_files=True))
    assert folders_payload.get("browse_via_index") is True
    folder_row = next(item for item in folders_payload["folders"] if item["name"] == "RJ01000001")
    assert folder_row["size"] == 9
    assert folder_row["size_status"] == "stale"
    assert folder_row["size_via_index"] is True

    completion_service = object.__new__(folder_completion_module.LibraryFolderCompletionService)
    completion_service.manager = manager
    completion_targets, completion_skipped = completion_service._resolve_selected_path_targets(library, str(circle_dir))
    assert completion_skipped == []
    assert [target.folder_path for target in completion_targets] == [str(rj_dir)]

    delete_preview = manager._local_delete(library, str(rj_dir), confirmed=False)
    assert delete_preview["browse_via_index"] is True
    assert delete_preview["size"] == 9
    assert delete_preview["size_status"] == "stale"
    assert delete_preview["index_refresh_pending"] is True
    assert delete_preview["file_count"] == 2
    assert delete_preview["folder_count"] == 2

    entries["Circle/RJ01000001"].size = 1024 * 1024
    entries["Circle/RJ01000001"].file_count = 99
    delete_preview = manager._local_delete(library, str(rj_dir), confirmed=False)
    assert delete_preview["browse_via_index"] is True
    assert delete_preview["size"] == 1024 * 1024
    assert delete_preview["file_count"] == 99

    batch_preview = manager._local_batch_delete(library, [str(rj_dir), str(circle_dir / "cover.jpg")], confirmed=False)
    assert batch_preview["browse_via_index"] is True
    assert batch_preview["total_size"] == 1024 * 1024 + 3
    assert batch_preview["total_file_count"] == 100
    assert batch_preview["total_folder_count"] == 2

    filter_preview = manager._local_filter_delete_preview(
        library,
        str(circle_dir),
        [{"name": "删 RJ 目录", "pattern": "RJ01000001", "target": "folder", "enabled": True}],
    )
    assert filter_preview["browse_via_index"] is True
    assert filter_preview["selected_count"] == 1
    assert filter_preview["selected_size"] == 4
    assert [item["relative_path"] for item in filter_preview["items"]] == [
        "RJ01000001",
        "RJ01000001/subtitles",
        "RJ01000001/subtitles/track.vtt",
    ]

    ledger_effects.clear()
    delete_result = manager._local_delete(library, str(circle_dir / "cover.jpg"), confirmed=True)
    assert delete_result["message"] == "删除成功"
    assert ledger_effects == [{
        "kind": "delete",
        "relative_path": "Circle/cover.jpg",
        "scope": "exact",
    }]
    assert "Circle/cover.jpg" not in entries
    folders_after_delete = asyncio.run(manager.list_local_folders_only(library.id, str(circle_dir), include_files=True))
    assert folders_after_delete.get("browse_via_index") is True
    assert [item["name"] for item in folders_after_delete["folders"]] == ["RJ01000001"]


def test_move_navigation_snapshot_uses_versioned_index_and_redis_cache(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    circle_path = library_root / "Circle"
    library = library_manager_module.LibraryDefinition(
        id="local-move-nav",
        name="移动导航",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    def entry(relative_path, entry_type):
        return IndexEntry(
            library_id=library.id,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(library_root / Path(relative_path)),
            name=relative_path.rsplit("/", 1)[-1],
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=10,
            file_count=1,
            mtime=1000,
            depth=relative_path.count("/") + 1,
            indexed_at=1000,
        )

    entries = {
        item.relative_path: item
        for item in [
            entry("Circle", "dir"),
            entry("Circle/RJ01000001", "dir"),
            entry("Circle/RJ01000001/track.wav", "file"),
        ]
    }

    class FakeIndexService:
        list_calls = 0

        def has_usable_snapshot(self, _library_id):
            return True

        def has_library_entries(self, _library_id):
            return True

        def get_status(self, _library_id):
            return SimpleNamespace(
                status="syncing",
                total_entries=3,
                active_generation=4,
                view_revision=9,
                accepted_seq=12,
                materialized_seq=11,
                state_revision=13,
            )

        def get_entry(self, _library_id, relative_path):
            return entries.get(relative_path)

        def list_children_page(self, _library_id, parent_path="", entry_type=None, **_kwargs):
            self.list_calls += 1
            rows = [item for item in entries.values() if (item.parent_path or "") == (parent_path or "")]
            if entry_type:
                rows = [item for item in rows if item.entry_type == entry_type]
            return {"entries": rows, "total": len(rows)}

    class FakeRedis:
        def __init__(self):
            self.values = {}

        def get_json(self, module, type_name, item_id):
            return self.values.get((module, type_name, item_id))

        def set_json(self, module, type_name, item_id, payload, **_kwargs):
            self.values[(module, type_name, item_id)] = payload
            return True

        def short_cache_ttl_seconds(self):
            return 60

    service = FakeIndexService()
    redis = FakeRedis()
    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_validate_local_index_entries_for_read", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("导航快照不得逐项校验磁盘")))
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: service)
    monkeypatch.setattr(redis_service_module, "get_redis_service", lambda: redis)

    first = manager.navigation_snapshot_via_index(library.id, str(circle_path), include_files=True)
    second = manager.navigation_snapshot_via_index(library.id, str(circle_path), include_files=True)

    assert first["browse_via_index"] is True
    assert first["cache_source"] == "postgresql"
    assert first["view_token"] == f"{library.id}:4:9"
    assert [item["name"] for item in first["folders"]] == ["RJ01000001"]
    assert [branch["relative_path"] for branch in first["tree_children"]] == ["", "Circle"]
    assert second["cache_source"] == "redis"
    assert service.list_calls == 2


def test_local_listing_counts_descendants_only_for_current_page(monkeypatch, tmp_path):
    local_root = tmp_path / "library"
    local_root.mkdir()
    for index in range(200):
        child = local_root / f"maker-{index:03d}"
        child.mkdir()
        (child / "track.mp3").write_bytes(b"audio")

    library = library_manager_module.LibraryDefinition(
        id="local-page",
        name="本地分页",
        type="local",
        path=str(local_root),
        enabled=True,
    )

    class FakeIndexService:
        def __init__(self):
            self.counted_paths = []

        def is_ready(self, library_id):
            return library_id == library.id

        def get_entry(self, library_id, relative_path):
            return IndexEntry(
                library_id=library_id,
                entry_type="dir",
                relative_path=relative_path,
                absolute_path=str(local_root / relative_path),
                name=relative_path,
                parent_path="",
                size=5,
                file_count=1,
                mtime=1000,
                depth=1,
                indexed_at=1000,
            )

        def count_descendant_dirs_many(self, library_id, relative_paths):
            self.counted_paths.extend(relative_paths)
            return {relative_path: 0 for relative_path in relative_paths}

    service = FakeIndexService()
    manager = object.__new__(library_manager_module.LibraryManager)
    manager._index_read_repair_lock = threading.Lock()
    manager._index_read_repair_last_seen = {}
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: service)

    result = manager._list_local_files(
        library,
        page=1,
        page_size=10,
        search="",
        current_path=str(local_root),
        sort_by="name",
        sort_order="asc",
    )

    assert result["total"] == 200
    assert len(result["files"]) == 10
    assert service.counted_paths == []
    assert all(item["folder_count"] is None for item in result["files"])
    assert all(item["folder_count_status"] == "lazy" for item in result["files"])


def test_list_files_coalesces_identical_inflight_requests(monkeypatch, tmp_path):
    local_root = tmp_path / "library"
    local_root.mkdir()
    library = library_manager_module.LibraryDefinition(
        id="local-coalesce",
        name="本地合并",
        type="local",
        path=str(local_root),
        enabled=True,
    )

    manager = object.__new__(library_manager_module.LibraryManager)
    manager._list_files_inflight_lock = None
    manager._list_files_inflight = {}
    call_count = 0

    def fake_list_local_files(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        threading.Event().wait(0.05)
        return {"files": [], "page": 1, "page_size": 100, "total": 0}

    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_list_local_files", fake_list_local_files)

    async def run_requests():
        return await asyncio.gather(
            manager.list_files(library.id, page=1, page_size=100, sort_by="name", sort_order="asc"),
            manager.list_files(library.id, page=1, page_size=100, sort_by="name", sort_order="asc"),
        )

    first, second = asyncio.run(run_requests())

    assert call_count == 1
    assert first == second
    assert first is not second


def test_search_files_via_index_supports_name_search_and_current_scope(monkeypatch, tmp_path):
    local_root = tmp_path / "library"
    circle_a = local_root / "CircleA"
    circle_b = local_root / "CircleB"
    work_a = circle_a / "RJ01000001 星の音声"
    work_b = circle_b / "RJ01000002 星の音声"
    work_a.mkdir(parents=True)
    work_b.mkdir(parents=True)
    (work_a / "track.wav").write_bytes(b"a")
    (work_b / "track.wav").write_bytes(b"b")

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(local_root),
        enabled=True,
    )

    def entry(relative_path, entry_type="dir", rjcode=None):
        return IndexEntry(
            library_id=library.id,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(local_root / Path(relative_path)),
            name=relative_path.rsplit("/", 1)[-1],
            rjcode=rjcode,
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=10,
            file_count=1 if entry_type == "dir" else 0,
            mtime=1000,
            depth=relative_path.count("/") + 1,
            indexed_at=1000,
        )

    indexed_entries = [
        entry("CircleA/RJ01000001 星の音声", rjcode="RJ01000001"),
        entry("CircleB/RJ01000002 星の音声", rjcode="RJ01000002"),
    ]

    class FakeIndexService:
        def is_ready(self, library_id):
            return library_id == library.id

        def find_by_name(self, library_id, name_like, entry_type=None, limit=200):
            assert name_like == "星の音声"
            return [item for item in indexed_entries if entry_type in (None, item.entry_type)]

        def find_by_rjcode(self, rjcode, library_id=None, entry_type="dir", limit=100):
            return [item for item in indexed_entries if item.rjcode == rjcode and entry_type in (None, item.entry_type)]

    manager = object.__new__(library_manager_module.LibraryManager)
    manager._local_search_result_cache = {}
    monkeypatch.setattr(manager, "load_config", lambda: {"local_search_cache_ttl_seconds": 0})
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: FakeIndexService())

    result = manager._search_local_files(
        library,
        page=1,
        page_size=20,
        search="星の音声",
        current_path=str(circle_a),
        sort_by="name",
        sort_order="asc",
        search_result_kind="folder",
    )

    assert result["search_via_index"] is True
    assert result["total"] == 1
    assert result["files"][0]["path"] == str(work_a)
    assert result["files"][0]["relative_path"] == "RJ01000001 星の音声"


def test_local_batch_rename_keeps_request_index_and_remaps_child_paths(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    parent = library_root / "old"
    parent.mkdir(parents=True)
    child = parent / "track.wav"
    child.write_bytes(b"demo")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_assert_local_path_in_library", lambda _library, _path: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    moved_items = []
    captured_sync = []
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda _source_library, _target_library, items, **kwargs: (
            moved_items.extend(items),
            captured_sync.append(kwargs.get("sync")),
        ),
    )
    monkeypatch.setattr(library_manager_module, "_stats_log_file_path", lambda: str(tmp_path / "stats.log"))

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    result = manager._local_batch_rename(library, [
        {"index": 3, "path": str(parent), "new_name": "new"},
        {"index": 4, "path": str(child), "new_name": "renamed.wav"},
    ])

    assert result["success_count"] == 2
    assert result["failed"] == []
    assert [item["index"] for item in result["results"]] == [3, 4]
    assert result["results"][1]["source_path"] == str(child)
    assert (library_root / "new" / "renamed.wav").exists()
    normalized_moves = [
        {
            "source": os.path.normcase(os.path.normpath(item["source"])),
            "destination": os.path.normcase(os.path.normpath(item["destination"])),
        }
        for item in moved_items
    ]
    assert normalized_moves == [
        {
            "source": os.path.normcase(os.path.normpath(str(parent))),
            "destination": os.path.normcase(os.path.normpath(str(library_root / "new"))),
        },
        {
            "source": os.path.normcase(os.path.normpath(str(library_root / "new" / "track.wav"))),
            "destination": os.path.normcase(os.path.normpath(str(library_root / "new" / "renamed.wav"))),
        },
    ]
    assert captured_sync == [False]


def test_local_batch_rename_can_skip_index_mutation(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    subtitle_dir = library_root / "_kikoerumanager_subtitle_workbench" / "linked" / "task" / "subtitles"
    subtitle_dir.mkdir(parents=True)
    source = subtitle_dir / "track1.vtt"
    source.write_text("WEBVTT", encoding="utf-8")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_assert_local_path_in_library", lambda _library, _path: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    moved_items = []
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda _source_library, _target_library, items, **_kwargs: moved_items.extend(items),
    )
    monkeypatch.setattr(library_manager_module, "_stats_log_file_path", lambda: str(tmp_path / "stats.log"))

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    result = manager._local_batch_rename(
        library,
        [{"index": 0, "path": str(source), "new_name": "track1.fixed.vtt"}],
        skip_index_mutation=True,
    )

    assert result["success_count"] == 1
    assert result["failed"] == []
    assert (subtitle_dir / "track1.fixed.vtt").exists()
    assert moved_items == []


def test_local_batch_rename_filters_workbench_subtitles_but_indexes_audio(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    work_dir = library_root / "RJ01000001"
    subtitle_dir = library_root / "_kikoerumanager_subtitle_workbench" / "linked" / "task" / "subtitles"
    work_dir.mkdir(parents=True)
    subtitle_dir.mkdir(parents=True)
    audio = work_dir / "track1.wav"
    subtitle = subtitle_dir / "track1.vtt"
    audio.write_bytes(b"audio")
    subtitle.write_text("WEBVTT", encoding="utf-8")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_assert_local_path_in_library", lambda _library, _path: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    moved_items = []
    captured_sync = []
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda _source_library, _target_library, items, **kwargs: (
            moved_items.extend(items),
            captured_sync.append(kwargs.get("sync")),
        ),
    )
    monkeypatch.setattr(library_manager_module, "_stats_log_file_path", lambda: str(tmp_path / "stats.log"))

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    result = manager._local_batch_rename(library, [
        {"index": 0, "path": str(audio), "new_name": "track-fixed.wav"},
        {"index": 1, "path": str(subtitle), "new_name": "track-fixed.vtt"},
    ])

    assert result["success_count"] == 2
    assert result["failed"] == []
    assert (work_dir / "track-fixed.wav").exists()
    assert (subtitle_dir / "track-fixed.vtt").exists()
    normalized_moves = [
        {
            "source": os.path.normcase(os.path.normpath(item["source"])),
            "destination": os.path.normcase(os.path.normpath(item["destination"])),
        }
        for item in moved_items
    ]
    assert normalized_moves == [
        {
            "source": os.path.normcase(os.path.normpath(str(audio))),
            "destination": os.path.normcase(os.path.normpath(str(work_dir / "track-fixed.wav"))),
        },
    ]
    assert captured_sync == [False]


def test_local_rename_filters_workbench_subtitle_index_mutation(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    subtitle_dir = library_root / "_kikoerumanager_subtitle_workbench" / "linked" / "task" / "subtitles"
    subtitle_dir.mkdir(parents=True)
    source = subtitle_dir / "track1.tmp.vtt"
    source.write_text("WEBVTT", encoding="utf-8")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_assert_local_path_in_library", lambda _library, _path: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    moved_items = []
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda _source_library, _target_library, items, **_kwargs: moved_items.extend(items),
    )
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    result = manager._local_rename(library, str(source), "track1.vtt")

    assert result["new_path"] == str(subtitle_dir / "track1.vtt")
    assert (subtitle_dir / "track1.vtt").exists()
    assert moved_items == []


def test_notify_index_move_batch_filters_workbench_subtitles_but_indexes_audio(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    work_dir = library_root / "RJ01000001"
    subtitle_dir = library_root / "_kikoerumanager_subtitle_workbench" / "linked" / "task" / "subtitles"
    work_dir.mkdir(parents=True)
    subtitle_dir.mkdir(parents=True)

    manager = object.__new__(library_manager_module.LibraryManager)
    captured = {}
    monkeypatch.setattr(
        manager,
        "get_library_definition",
        lambda _library_id: library_manager_module.LibraryDefinition(
            id="local-a",
            name="本地 A",
            type="local",
            path=str(library_root),
            enabled=True,
        ),
    )

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(operation_id="subtitle-move-operation")

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return kwargs["actual_result"]

    monkeypatch.setattr(library_index_module, "get_library_index_mutation_service", lambda: FakeMutationService())
    result = manager.notify_index_move_batch("local-a", [
        {
            "source": str(work_dir / "old.wav"),
            "destination": str(work_dir / "new.wav"),
        },
        {
            "source": str(subtitle_dir / "old.vtt"),
            "destination": str(subtitle_dir / "new.vtt"),
        },
    ])

    assert result["submitted"] is True
    assert result["submitted_count"] == 1
    assert result["queued"] is False
    assert result["queued_count"] == 0
    assert result["filtered_count"] == 1
    assert result["total_count"] == 2
    assert captured["filesystem_started"] == "subtitle-move-operation"
    assert captured["finalize"]["actual_effects_by_library"]["local-a"] == [
        {
            "kind": "move",
            "relative_path": "RJ01000001/old.wav",
            "scope": "exact",
            "target_library_id": "local-a",
            "target_path": "RJ01000001/new.wav",
            "payload": {
                "old_absolute_path": str(work_dir / "old.wav"),
                "new_absolute_path": str(work_dir / "new.wav"),
            },
        },
        {
            "kind": "move_target",
            "relative_path": "RJ01000001/new.wav",
            "scope": "exact",
            "payload": {
                "source_library_id": "local-a",
                "source_path": "RJ01000001/old.wav",
                "old_absolute_path": str(work_dir / "old.wav"),
                "new_absolute_path": str(work_dir / "new.wav"),
            },
        },
    ]


def test_local_move_preview_allows_same_name_folder_merge(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_parent = library_root / "source"
    target_parent = library_root / "target"
    source_dir = source_parent / "Circle"
    target_dir = target_parent / "Circle"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    (source_dir / "new.wav").write_bytes(b"new")
    (target_dir / "old.wav").write_bytes(b"old")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_local_top_level_delta", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    monkeypatch.setattr(manager, "_notify_index_self_mutation_move_batch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_notify_index_self_mutation_delete_batch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_enqueue_index_replace_subtree_many", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    preview = manager._preview_move_local_items_sync(
        library,
        library,
        [str(source_dir)],
        str(target_parent),
    )
    assert preview["conflict_count"] == 0
    assert preview["merge_folder_count"] == 1

    result = manager._move_local_items_sync(
        library,
        library,
        [str(source_dir)],
        str(target_parent),
        "suffix",
    )

    assert result["success_count"] == 1
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 0
    assert not source_dir.exists()
    assert (target_dir / "old.wav").read_bytes() == b"old"
    assert (target_dir / "new.wav").read_bytes() == b"new"


def test_local_move_returns_index_fence_for_frontend_refresh(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_dir = library_root / "[Circle][RJ123456] Work"
    target_dir = library_root / "Circle"
    source_dir.mkdir(parents=True)
    target_dir.mkdir()
    (source_dir / "track.wav").write_bytes(b"audio")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_local_top_level_delta", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    monkeypatch.setattr(manager, "_notify_index_self_mutation_delete_batch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_enqueue_index_replace_subtree_many", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda *_args, **_kwargs: {
            "operation_id": "circle-move-operation",
            "operation_state": "committed",
            "index_fences": [{
                "library_id": "local-a",
                "accepted_seq": 12,
                "materialized_seq": 11,
            }],
        },
    )

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    result = manager._move_local_items_sync(
        library,
        library,
        [str(source_dir)],
        str(target_dir),
        "suffix",
    )

    assert result["operation_id"] == "circle-move-operation"
    assert result["operation_state"] == "committed"
    assert result["index_fences"][0]["accepted_seq"] == 12
    assert result["moved"][0]["destination"] == str(target_dir / source_dir.name)


def test_record_index_move_many_returns_finalize_response(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_path = library_root / "old" / "RJ123456"
    destination = library_root / "Circle" / "RJ123456"
    destination.mkdir(parents=True)

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )
    manager = object.__new__(library_manager_module.LibraryManager)
    captured = {}

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(operation_id="circle-move-operation")

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": library.id, "accepted_seq": 12}],
            }

    monkeypatch.setattr(
        library_index_module,
        "get_library_index_mutation_service",
        lambda: FakeMutationService(),
    )

    response = manager._record_index_move_many(
        library,
        library,
        [{"source": str(source_path), "destination": str(destination)}],
        source="self_mutation_move",
    )

    assert response["operation_id"] == "circle-move-operation"
    assert response["index_fences"][0]["accepted_seq"] == 12
    effects = captured["finalize"]["actual_effects_by_library"][library.id]
    assert [effect["kind"] for effect in effects] == ["move", "move_target"]
    assert effects[0]["payload"] == {
        "old_absolute_path": str(source_path),
        "new_absolute_path": str(destination),
    }


def test_local_move_preview_prefers_index_and_versions_redis_plan(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_dir = library_root / "source" / "Circle"
    target_dir = library_root / "target" / "Circle"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    (source_dir / "new.wav").write_bytes(b"new")
    (source_dir / "track.wav").write_bytes(b"source")
    (target_dir / "old.wav").write_bytes(b"old")
    (target_dir / "track.wav").write_bytes(b"target")

    library = library_manager_module.LibraryDefinition(
        id="local-index-preview",
        name="索引预检",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    def entry(relative_path, entry_type):
        return IndexEntry(
            library_id=library.id,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(library_root / Path(relative_path)),
            name=relative_path.rsplit("/", 1)[-1],
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=1,
            file_count=1,
            mtime=1000,
            depth=relative_path.count("/") + 1,
            indexed_at=1000,
        )

    entries = {
        item.relative_path: item
        for item in [
            entry("source", "dir"),
            entry("source/Circle", "dir"),
            entry("source/Circle/new.wav", "file"),
            entry("source/Circle/track.wav", "file"),
            entry("target", "dir"),
            entry("target/Circle", "dir"),
            entry("target/Circle/old.wav", "file"),
            entry("target/Circle/track.wav", "file"),
        ]
    }

    class FakeIndexService:
        view_revision = 7

        def get_status(self, _library_id):
            return SimpleNamespace(
                active_generation=2,
                view_revision=self.view_revision,
                accepted_seq=5,
                materialized_seq=5,
                state_revision=8,
            )

        def get_entry(self, _library_id, relative_path):
            return entries.get(relative_path)

        def list_subtree_entries(self, _library_id, relative_path, **_kwargs):
            return [
                item for item in entries.values()
                if item.relative_path == relative_path or item.relative_path.startswith(relative_path + "/")
            ]

    class FakeRedis:
        def __init__(self):
            self.values = {}

        def set_json(self, module, type_name, item_id, payload, **_kwargs):
            self.values[(module, type_name, item_id)] = payload
            return True

        def get_json(self, module, type_name, item_id):
            return self.values.get((module, type_name, item_id))

        def short_cache_ttl_seconds(self):
            return 60

    service = FakeIndexService()
    redis = FakeRedis()
    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_index_service_if_ready", lambda _library: service)
    monkeypatch.setattr(redis_service_module, "get_redis_service", lambda: redis)

    preview = manager._preview_move_local_items_via_index(
        library,
        library,
        [str(source_dir)],
        str(library_root / "target"),
    )

    assert preview["preview_source"] == "index"
    assert preview["conflict_count"] == 1
    assert preview["conflicts"][0]["relative_path"].replace("\\", "/") == "Circle/track.wav"
    assert preview["merge_folder_count"] == 1
    assert preview["move_plan_id"]
    assert manager.validate_move_preview_plan(
        preview["move_plan_id"],
        source_library_id=library.id,
        target_library_id=library.id,
        paths=[str(source_dir)],
        target_path=str(library_root / "target"),
    ) is True

    service.view_revision = 8
    assert manager.validate_move_preview_plan(
        preview["move_plan_id"],
        source_library_id=library.id,
        target_library_id=library.id,
        paths=[str(source_dir)],
        target_path=str(library_root / "target"),
    ) is False


def test_local_move_index_preview_uses_platform_filename_case_semantics(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_dir = library_root / "source" / "Circle"
    target_dir = library_root / "target" / "Circle"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    (source_dir / "Track.wav").write_bytes(b"source")
    (target_dir / "track.wav").write_bytes(b"target")

    library = library_manager_module.LibraryDefinition(
        id="local-case-preview",
        name="大小写冲突预检",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    def entry(relative_path, entry_type):
        return IndexEntry(
            library_id=library.id,
            entry_type=entry_type,
            relative_path=relative_path,
            absolute_path=str(library_root / Path(relative_path)),
            name=relative_path.rsplit("/", 1)[-1],
            parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
            size=1,
            file_count=1,
            mtime=1000,
            depth=relative_path.count("/") + 1,
            indexed_at=1000,
        )

    entries = {
        item.relative_path: item
        for item in [
            entry("source", "dir"),
            entry("source/Circle", "dir"),
            entry("source/Circle/Track.wav", "file"),
            entry("target", "dir"),
            entry("target/Circle", "dir"),
            entry("target/Circle/track.wav", "file"),
        ]
    }

    class FakeIndexService:
        def get_status(self, _library_id):
            return SimpleNamespace(
                active_generation=1,
                view_revision=1,
                accepted_seq=1,
                materialized_seq=1,
                state_revision=1,
            )

        def get_entry(self, _library_id, relative_path):
            return entries.get(relative_path)

        def list_subtree_entries(self, _library_id, relative_path, **_kwargs):
            return [
                item for item in entries.values()
                if item.relative_path == relative_path or item.relative_path.startswith(relative_path + "/")
            ]

    manager = object.__new__(library_manager_module.LibraryManager)
    service = FakeIndexService()
    monkeypatch.setattr(manager, "_index_service_if_ready", lambda _library: service)
    monkeypatch.setattr(manager, "_store_move_preview_plan", lambda payload: payload)

    preview = manager._preview_move_local_items_via_index(
        library,
        library,
        [str(source_dir)],
        str(library_root / "target"),
    )

    case_insensitive = os.path.normcase("Track.wav") == os.path.normcase("track.wav")
    assert preview["conflict_count"] == (1 if case_insensitive else 0)
    if case_insensitive:
        assert preview["conflicts"][0]["relative_path"].replace("\\", "/") == "Circle/Track.wav"


def test_local_move_preview_reports_child_file_conflict_before_folder_merge(monkeypatch, tmp_path):
    library_root = tmp_path / "library"
    source_parent = library_root / "source"
    target_parent = library_root / "target"
    source_dir = source_parent / "Circle"
    target_dir = target_parent / "Circle"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    (source_dir / "track.wav").write_bytes(b"new")
    (target_dir / "track.wav").write_bytes(b"old")

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "_local_top_level_delta", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_invalidate_local_search_cache", lambda _library_id: None)
    monkeypatch.setattr(manager, "_notify_index_self_mutation_move_batch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_notify_index_self_mutation_delete_batch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_enqueue_index_replace_subtree_many", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)

    library = library_manager_module.LibraryDefinition(
        id="local-a",
        name="本地 A",
        type="local",
        path=str(library_root),
        enabled=True,
    )

    preview = manager._preview_move_local_items_sync(
        library,
        library,
        [str(source_dir)],
        str(target_parent),
    )
    assert preview["conflict_count"] == 1
    assert preview["conflicts"][0]["relative_path"].replace("\\", "/") == "Circle/track.wav"

    result = manager._move_local_items_sync(
        library,
        library,
        [str(source_dir)],
        str(target_parent),
        "suffix",
    )

    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert not source_dir.exists()
    assert (target_dir / "track.wav").read_bytes() == b"old"
    assert (target_dir / "track_1.wav").read_bytes() == b"new"


@pytest.mark.parametrize(("existing_on_lookup", "expect_plan_checked"), [(1, False), (2, True)])
def test_library_browser_move_replays_committed_request_around_stale_plan_check(
    monkeypatch,
    tmp_path,
    existing_on_lookup,
    expect_plan_checked,
):
    library_root = tmp_path / "library"
    source_path = library_root / "source" / "Circle"
    target_path = library_root / "target"
    source_path.mkdir(parents=True)
    target_path.mkdir(parents=True)
    captured = {}

    library = SimpleNamespace(
        id="local-a",
        type="local",
        root_path=str(library_root),
    )

    class FakeLibraryManager:
        def get_library_definition(self, _library_id):
            return library

        def validate_move_preview_plan(self, *_args, **_kwargs):
            captured["plan_checked"] = True
            return False

        async def move_local_items(self, **_kwargs):
            raise AssertionError("幂等回放不应再次执行文件系统移动")

    class FakeMutationService:
        def get_operation_by_idempotency_key(self, idempotency_key):
            captured["lookup_key"] = idempotency_key
            captured["lookup_count"] = captured.get("lookup_count", 0) + 1
            if captured["lookup_count"] < existing_on_lookup:
                return None
            return {"operation_id": "move-operation"}

        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="move-operation",
                replayed=True,
                state="committed",
                result={
                    "operation_id": "move-operation",
                    "operation_state": "committed",
                    "success_count": 1,
                },
            )

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())

    response = asyncio.run(routes_module.move_library_browser_items(
        routes_module.LibraryBrowserMoveRequest(
            source_library_id=library.id,
            target_library_id=library.id,
            paths=[str(source_path)],
            target_path=str(target_path),
            move_plan_id="stale-plan",
        ),
        _FakeJsonRequest({}, headers={"Idempotency-Key": "move-key"}),
    ))

    assert response["operation_state"] == "committed"
    assert response["success_count"] == 1
    assert captured["lookup_key"] == "move-key"
    assert captured["prepare"]["idempotency_key"] == "move-key"
    assert ("plan_checked" in captured) is expect_plan_checked


def test_subtitle_manual_match_rename_can_skip_index_mutation(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        async def rename(self, library_id, path, new_name, *, skip_index_mutation=False, sync_index_mutation=False):
            captured["library_id"] = library_id
            captured["path"] = path
            captured["new_name"] = new_name
            captured["skip_index_mutation"] = skip_index_mutation
            captured["sync_index_mutation"] = sync_index_mutation
            return {"message": "重命名成功", "new_path": path.replace("old.vtt", "new.vtt")}

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())

    response = asyncio.run(
        routes_module.rename_library_browser_item(_FakeJsonRequest({
            "library_id": "local-a",
            "path": "/library/workbench/old.vtt",
            "new_name": "new.vtt",
            "skip_activity_log": True,
            "rename_context": "subtitle_manual_match_pair",
            "skip_index_mutation": True,
        }))
    )

    assert response["new_path"] == "/library/workbench/new.vtt"
    assert captured["library_id"] == "local-a"
    assert captured["skip_index_mutation"] is True
    assert captured["sync_index_mutation"] is False


def test_library_browser_rename_uses_mutation_fence_by_default(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            return SimpleNamespace(
                id=library_id,
                type="local",
                root_path="/library",
            )

        async def rename(self, library_id, path, new_name, *, skip_index_mutation=False, sync_index_mutation=False):
            captured["library_id"] = library_id
            captured["path"] = path
            captured["new_name"] = new_name
            captured["skip_index_mutation"] = skip_index_mutation
            captured["sync_index_mutation"] = sync_index_mutation
            return {"message": "重命名成功", "new_path": path.replace("old", "new")}

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="rename-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                **kwargs["actual_result"],
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": "local-a", "accepted_seq": 1}],
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.rename_library_browser_item(_FakeJsonRequest(
            {
                "library_id": "local-a",
                "path": "/library/work/old",
                "new_name": "new",
                "skip_activity_log": True,
            },
            headers={"Idempotency-Key": "rename-key"},
        ))
    )

    assert response["new_path"] == "/library/work/new"
    assert response["operation_state"] == "committed"
    assert captured["filesystem_started"] == "rename-operation"
    assert captured["skip_index_mutation"] is True
    assert captured["sync_index_mutation"] is False
    assert captured["prepare"]["idempotency_key"] == "rename-key"
    assert captured["finalize"]["actual_effects_by_library"]["local-a"] == [
        {
            "kind": "move",
            "relative_path": "work/old",
            "scope": "exact",
            "target_library_id": "local-a",
            "target_path": "work/new",
        },
        {
            "kind": "reconcile",
            "relative_path": "work/new",
            "scope": "exact",
        },
    ]


def test_subtitle_manual_match_batch_rename_can_skip_index_mutation(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        async def batch_rename(self, library_id, items, *, skip_index_mutation=False, sync_index_mutation=False):
            captured["library_id"] = library_id
            captured["items"] = items
            captured["skip_index_mutation"] = skip_index_mutation
            captured["sync_index_mutation"] = sync_index_mutation
            return {
                "results": [
                    {
                        "index": item["index"],
                        "path": item["path"],
                        "source_path": item["path"],
                        "new_name": item["new_name"],
                        "new_path": item["path"].replace("old.vtt", "new.vtt"),
                    }
                    for item in items
                ],
                "failed": [],
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())

    response = asyncio.run(
        routes_module.batch_rename_library_browser_items(_FakeJsonRequest({
            "library_id": "local-a",
            "items": [{"path": "/library/workbench/old.vtt", "new_name": "new.vtt"}],
            "skip_activity_log": True,
            "rename_context": "subtitle_manual_match_pair",
            "skip_index_mutation": True,
        }))
    )

    assert response["success_count"] == 1
    assert captured["library_id"] == "local-a"
    assert captured["skip_index_mutation"] is True
    assert captured["sync_index_mutation"] is False


def test_library_browser_batch_rename_syncs_index_by_default(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            return SimpleNamespace(
                id=library_id,
                type="local",
                root_path="/library",
            )

        async def batch_rename(self, library_id, items, *, skip_index_mutation=False, sync_index_mutation=False):
            captured["library_id"] = library_id
            captured["items"] = items
            captured["skip_index_mutation"] = skip_index_mutation
            captured["sync_index_mutation"] = sync_index_mutation
            return {
                "results": [
                    {
                        "index": item["index"],
                        "path": item["path"],
                        "source_path": item["path"],
                        "new_name": item["new_name"],
                        "new_path": item["path"].replace("old", "new"),
                    }
                    for item in items
                ],
                "failed": [],
            }

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="batch-rename-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                **kwargs["actual_result"],
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": "local-a", "accepted_seq": 1}],
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)
    monkeypatch.setattr("app.core.activity_log_service.log_batch_manual_rename_result", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.batch_rename_library_browser_items(_FakeJsonRequest(
            {
                "library_id": "local-a",
                "items": [{"path": "/library/work/old", "new_name": "new", "current_name": "old"}],
                "skip_activity_log": True,
            },
            headers={"Idempotency-Key": "batch-rename-key"},
        ))
    )

    assert response["success_count"] == 1
    assert response["operation_state"] == "committed"
    assert captured["filesystem_started"] == "batch-rename-operation"
    assert captured["skip_index_mutation"] is True
    assert captured["sync_index_mutation"] is False
    assert captured["prepare"]["idempotency_key"] == "batch-rename-key"
    assert captured["finalize"]["actual_effects_by_library"]["local-a"] == [
        {
            "kind": "move",
            "relative_path": "work/old",
            "scope": "exact",
            "target_library_id": "local-a",
            "target_path": "work/new",
        },
        {
            "kind": "reconcile",
            "relative_path": "work/new",
            "scope": "exact",
        },
    ]


def test_cross_library_batch_delete_fence_contains_only_success_targets(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            return SimpleNamespace(
                id=library_id,
                type="local",
                root_path=f"/library/{library_id}",
            )

        async def batch_delete_targets(self, targets, confirmed=False, *, skip_index_mutation=False):
            captured["skip_index_mutation"] = skip_index_mutation
            return {
                "message": "批量删除完成",
                "success_count": 1,
                "success_paths": [{"library_id": "library-a", "path": "/library/library-a/ok"}],
                "failed_paths": [{
                    "library_id": "library-b",
                    "path": "/library/library-b/failed",
                    "error": "locked",
                }],
            }

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="batch-delete-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                **kwargs["actual_result"],
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": "library-a", "accepted_seq": 1}],
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())

    response = asyncio.run(
        routes_module.batch_delete_library_browser_targets(_FakeJsonRequest(
            {
                "confirmed": True,
                "skip_activity_log": True,
                "targets": [
                    {"library_id": "library-a", "path": "/library/library-a/ok"},
                    {"library_id": "library-b", "path": "/library/library-b/failed"},
                ],
            },
            headers={"Idempotency-Key": "cross-delete-key"},
        ))
    )

    assert response["operation_state"] == "committed"
    assert captured["filesystem_started"] == "batch-delete-operation"
    assert captured["skip_index_mutation"] is True
    assert captured["prepare"]["idempotency_key"] == "cross-delete-key"
    assert set(captured["prepare"]["effects_by_library"]) == {"library-a", "library-b"}
    assert captured["finalize"]["actual_effects_by_library"] == {
        "library-a": [{
            "kind": "delete",
            "relative_path": "ok",
            "scope": "exact",
        }],
    }


def test_api_rename_locks_metadata_to_target_folder_rjcode(monkeypatch):
    captured = {}

    class FakeLibrary:
        id = "remote-a"
        type = "synology_filestation"

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            captured["requested_library_id"] = library_id
            return FakeLibrary()

        async def rename(self, library_id, path, new_name, *, sync_index_mutation=False):
            captured["rename"] = {
                "library_id": library_id,
                "path": path,
                "new_name": new_name,
                "sync_index_mutation": sync_index_mutation,
            }
            return {
                "message": "重命名成功",
                "new_path": "/library_amsr/青春/[青春][RJ01570159]/[青春][RJ01572763]",
            }

    class FakeMetadataService:
        async def fetch(self, path, task, force_refresh=False):
            captured["metadata_path"] = path
            captured["metadata_task_rjcode"] = task.rjcode
            captured["metadata_task_metadata"] = dict(task.task_metadata)
            return {
                "rjcode": "RJ01572763",
                "work_name": "目标作品",
                "maker_name": "青春",
                "cvs": [],
                "metadata_evidence_source": "dlsite_product",
            }

    class FakeRenameService:
        async def _get_japanese_metadata(self, rjcode):
            captured["japanese_rjcode"] = rjcode
            return {"maker_name": "青春", "cvs": []}

        def _compile_name(self, metadata, japanese_metadata):
            return f"[{japanese_metadata['maker_name']}][{metadata['rjcode']}]"

        def _sanitize_filename(self, value):
            return value

    class FakeDb:
        def query(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def delete(self):
            return 0

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    fake_config = SimpleNamespace(
        rename=SimpleNamespace(
            template="[{maker_name}][{rjcode}]",
            api_rename_follow_template=True,
            use_japanese_metadata=True,
        )
    )

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_config", lambda: fake_config)
    monkeypatch.setattr(routes_module, "get_db", lambda: iter([FakeDb()]))
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.rename_service.RenameService", lambda: FakeRenameService())
    monkeypatch.setattr("app.models.database.get_db", lambda: iter([FakeDb()]))
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.api_rename_library_file(_FakeJsonRequest({
            "library_id": "remote-a",
            "path": "/library_amsr/青春/[青春][RJ01570159]/RJ01572763",
        }))
    )

    assert response["new_name"] == "[青春][RJ01572763]"
    assert captured["metadata_task_rjcode"] == "RJ01572763"
    assert captured["metadata_task_metadata"] == {
        "rjcode": "RJ01572763",
        "rjcode_lock": True,
    }
    assert captured["japanese_rjcode"] == "RJ01572763"
    assert captured["rename"]["new_name"] == "[青春][RJ01572763]"
    assert captured["rename"]["sync_index_mutation"] is True


def test_local_api_rename_commits_mutation_fence(monkeypatch, tmp_path):
    captured = {}
    root = tmp_path / "library"
    source = root / "RJ01572763 old"
    source.mkdir(parents=True)
    library = SimpleNamespace(id="local-a", type="local", root_path=str(root))

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            assert library_id == library.id
            return library

        async def rename(self, library_id, path, new_name, **kwargs):
            captured["rename"] = {
                "library_id": library_id,
                "path": path,
                "new_name": new_name,
                **kwargs,
            }
            return {"message": "重命名成功", "new_path": str(root / new_name)}

    class FakeMetadataService:
        async def fetch(self, _path, task, force_refresh=False):
            assert force_refresh is False
            return {
                "rjcode": task.rjcode,
                "work_name": "目标作品",
                "maker_name": "目标社团",
                "cvs": [],
                "metadata_evidence_source": "dlsite_product",
            }

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="api-rename-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                **kwargs["actual_result"],
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": library.id, "accepted_seq": 1}],
            }

        def fail_prepared(self, *_args, **_kwargs):
            raise AssertionError("成功重命名不应回滚 prepared operation")

        def mark_reconcile_required(self, *_args, **_kwargs):
            raise AssertionError("成功重命名不应进入 reconcile_required")

    class FakeRenameService:
        async def _get_japanese_metadata(self, _rjcode):
            raise AssertionError("未启用日语元数据时不应请求")

        def _compile_name(self, metadata, japanese_metadata):
            assert japanese_metadata is None
            return f"[{metadata['maker_name']}][{metadata['rjcode']}]"

        def _sanitize_filename(self, value):
            return value

    fake_config = SimpleNamespace(
        rename=SimpleNamespace(
            template="[{maker_name}][{rjcode}]",
            api_rename_follow_template=False,
            use_japanese_metadata=False,
        )
    )
    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())
    monkeypatch.setattr(routes_module, "get_config", lambda: fake_config)
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.rename_service.RenameService", lambda: FakeRenameService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    response = asyncio.run(routes_module.api_rename_library_file(_FakeJsonRequest(
        {"library_id": library.id, "path": str(source)},
        headers={"Idempotency-Key": "api-rename-key"},
    )))

    assert response["operation_state"] == "committed"
    assert captured["filesystem_started"] == "api-rename-operation"
    assert captured["prepare"]["idempotency_key"] == "api-rename-key"
    assert captured["rename"]["skip_index_mutation"] is True
    assert captured["rename"]["sync_index_mutation"] is False
    assert captured["finalize"]["actual_effects_by_library"][library.id] == [
        {
            "kind": "move",
            "relative_path": source.name,
            "scope": "subtree",
            "target_library_id": library.id,
            "target_path": "[目标社团][RJ01572763]",
        },
        {
            "kind": "reconcile",
            "relative_path": "[目标社团][RJ01572763]",
            "scope": "subtree",
        },
    ]


def test_api_rename_rejects_minimal_metadata_without_renaming(monkeypatch):
    captured = {}

    class FakeLibrary:
        id = "remote-a"
        type = "synology_filestation"

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            return FakeLibrary()

        async def rename(self, *_args, **_kwargs):
            captured["rename_called"] = True
            raise AssertionError("元数据不可用时不应执行重命名")

    class FakeMetadataService:
        async def fetch(self, path, task, force_refresh=False):
            captured["metadata_task_rjcode"] = task.rjcode
            captured["force_refresh"] = force_refresh
            return {
                "rjcode": "RJ01572763",
                "work_name": "RJ01572763",
                "maker_name": "",
                "tags": [],
                "cvs": [],
                "cover_url": "",
                "release_date": "",
                "metadata_source": "minimal",
                "dlsite_circuit_open": False,
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.api_rename_library_file(_FakeJsonRequest({
            "library_id": "remote-a",
            "path": "/library_amsr/青春/RJ01572763",
        }))
    )
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["skipped"] is True
    assert payload["metadata_verification_status"] == "unverified"
    assert "元数据" in payload["detail"]
    assert captured["metadata_task_rjcode"] == "RJ01572763"
    assert captured["force_refresh"] is False
    assert "rename_called" not in captured


def test_api_rename_normalizes_markdown_rjcode_before_metadata_fetch(monkeypatch):
    captured = {}

    class FakeLibrary:
        id = "remote-a"
        type = "synology_filestation"

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            return FakeLibrary()

        async def rename(self, *_args, **_kwargs):
            captured["rename_called"] = True
            raise AssertionError("本测试只验证元数据请求前的 RJ 归一化")

    class FakeMetadataService:
        async def fetch(self, path, task, force_refresh=False):
            captured["metadata_task_rjcode"] = task.rjcode
            captured["metadata_task_metadata"] = dict(task.task_metadata)
            return {
                "rjcode": "RJ01649758",
                "work_name": "RJ01649758",
                "maker_name": "",
                "tags": [],
                "cvs": [],
                "cover_url": "",
                "release_date": "",
                "metadata_source": "minimal",
                "dlsite_circuit_open": False,
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    markdown_path = "/library_amsr/[RJ01649758](https://www.dlsite.com/maniax/work/=/product_id/RJ01649758.html)"
    response = asyncio.run(
        routes_module.api_rename_library_file(_FakeJsonRequest({
            "library_id": "remote-a",
            "path": markdown_path,
        }))
    )

    assert response.status_code == 422
    assert captured["metadata_task_rjcode"] == "RJ01649758"
    assert captured["metadata_task_metadata"] == {
        "rjcode": "RJ01649758",
        "rjcode_lock": True,
    }
    assert "rename_called" not in captured


def test_metadata_service_normalizes_locked_markdown_rjcode(monkeypatch):
    captured = {}
    service = MetadataService()
    service.config.metadata.cache_enabled = False

    async def fake_fetch_from_dlsite_product_info(rjcode):
        captured["rjcode"] = rjcode
        metadata = SimpleNamespace(
            metadata_source="minimal",
            to_dict=lambda: {
                "rjcode": rjcode,
                "metadata_source": "minimal",
            },
        )
        return metadata

    monkeypatch.setattr(service, "_fetch_from_dlsite_product_info", fake_fetch_from_dlsite_product_info)

    task = SimpleNamespace(
        rjcode="[RJ01649758](https://www.dlsite.com/maniax/work/=/product_id/RJ01649758.html)",
        task_metadata={
            "rjcode": "[RJ01649758](https://www.dlsite.com/maniax/work/=/product_id/RJ01649758.html)",
            "rjcode_lock": True,
        },
        update_progress=lambda *_args, **_kwargs: None,
    )

    result = asyncio.run(service.fetch("/library/no-rj-here", task))

    assert captured["rjcode"] == "RJ01649758"
    assert result["rjcode"] == "RJ01649758"


def test_metadata_service_accepts_null_dlsite_release_date(monkeypatch):
    service = MetadataService()

    async def fake_resolve_original_maker_fields(product, rjcode):
        return {
            "maker_id": product.get("maker_id", ""),
            "maker_name": product.get("maker_name", ""),
        }

    async def fake_apply_dlsite_bonus_info(metadata, rjcode):
        return None

    monkeypatch.setattr(service, "_resolve_original_maker_fields", fake_resolve_original_maker_fields)
    monkeypatch.setattr(service, "_apply_dlsite_bonus_info", fake_apply_dlsite_bonus_info)

    metadata = asyncio.run(
        service._build_metadata_from_dlsite_product(
            "RJ01649758",
            {
                "workno": "RJ01649758",
                "work_name": "限定イラスト",
                "maker_id": "RG60152",
                "maker_name": "おいしいおこめ",
                "regist_date": None,
                "image_main": {"url": "//img.dlsite.jp/modpub/images2/work/sample.jpg"},
                "genres": [],
                "creaters": [],
            },
        )
    )

    assert metadata.rjcode == "RJ01649758"
    assert metadata.release_date == ""
    assert metadata.maker_name == "おいしいおこめ"


def test_batch_api_rename_skips_minimal_metadata_without_batch_renaming(monkeypatch):
    routes_module._BATCH_API_RENAME_INFLIGHT.clear()
    captured = {}

    class FakeLibrary:
        id = "remote-a"
        type = "synology_filestation"

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            captured["library_id"] = library_id
            return FakeLibrary()

        async def batch_rename(self, *_args, **_kwargs):
            captured["batch_rename_called"] = True
            raise AssertionError("元数据不可用时不应执行批量重命名")

    class FakeMetadataService:
        async def fetch(self, path, task, force_refresh=False):
            captured["metadata_task_rjcode"] = task.rjcode
            captured["metadata_task_metadata"] = dict(task.task_metadata)
            return {
                "rjcode": "RJ01572763",
                "work_name": "RJ01572763",
                "maker_name": "",
                "tags": [],
                "cvs": [],
                "cover_url": "",
                "release_date": "",
                "metadata_source": "minimal",
                "dlsite_circuit_open": True,
            }

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)
    monkeypatch.setattr("app.core.activity_log_service.log_batch_api_rename_result", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.batch_api_rename_library_items(
            _FakeJsonRequest({
                "library_id": "remote-a",
                "paths": ["/library_amsr/青春/RJ01572763"],
            }),
            None,
        )
    )

    assert response["success_count"] == 0
    assert response["failed_count"] == 1
    assert response["results"][0]["success"] is False
    assert response["results"][0]["skipped"] is True
    assert "DLsite 元数据短熔断中" in response["results"][0]["error"]
    assert response["results"][0]["metadata_source"] == "minimal"
    assert response["results"][0]["metadata_verification_status"] == "unverified"
    assert (
        response["results"][0]["metadata_verification_reason"]
        == "元数据来源缺少可验证的结构化证据"
    )
    assert captured["metadata_task_rjcode"] == "RJ01572763"
    assert captured["metadata_task_metadata"] == {
        "rjcode": "RJ01572763",
        "rjcode_lock": True,
    }
    assert "batch_rename_called" not in captured


def test_local_batch_api_rename_fence_contains_only_successful_items(monkeypatch, tmp_path):
    routes_module._BATCH_API_RENAME_INFLIGHT.clear()
    captured = {}
    root = tmp_path / "library"
    first = root / "RJ01000001 old"
    second = root / "RJ01000002 old"
    first.mkdir(parents=True)
    second.mkdir()
    library = SimpleNamespace(id="local-a", type="local", root_path=str(root))

    class FakeLibraryManager:
        def get_library_definition(self, library_id):
            assert library_id == library.id
            return library

        async def batch_rename(self, library_id, items, **kwargs):
            captured["batch_rename"] = {
                "library_id": library_id,
                "items": items,
                **kwargs,
            }
            return {
                "success_count": 1,
                "results": [{
                    "index": 0,
                    "path": items[0]["path"],
                    "new_name": items[0]["new_name"],
                    "new_path": str(root / items[0]["new_name"]),
                }],
                "failed": [{
                    "index": 1,
                    "path": items[1]["path"],
                    "new_name": items[1]["new_name"],
                    "error": "locked",
                }],
            }

    class FakeMetadataService:
        async def fetch(self, _path, task, force_refresh=False):
            return {
                "rjcode": task.rjcode,
                "work_name": f"作品 {task.rjcode}",
                "maker_name": "目标社团",
                "cvs": [],
                "metadata_evidence_source": "dlsite_product",
            }

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(
                operation_id="batch-api-rename-operation",
                replayed=False,
                state="prepared",
                result=None,
            )

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return {
                **kwargs["actual_result"],
                "operation_id": operation_id,
                "operation_state": "committed",
                "index_fences": [{"library_id": library.id, "accepted_seq": 1}],
            }

        def mark_reconcile_required(self, *_args, **_kwargs):
            raise AssertionError("确定的部分失败不应进入 reconcile_required")

    class FakeRenameService:
        async def _get_japanese_metadata(self, _rjcode):
            raise AssertionError("未启用日语元数据时不应请求")

        def _compile_name(self, metadata, japanese_metadata):
            assert japanese_metadata is None
            return f"[{metadata['maker_name']}][{metadata['rjcode']}]"

        def _sanitize_filename(self, value):
            return value

    fake_config = SimpleNamespace(
        rename=SimpleNamespace(
            template="[{maker_name}][{rjcode}]",
            api_rename_follow_template=False,
            use_japanese_metadata=False,
        )
    )
    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr(routes_module, "get_library_index_mutation_service", lambda: FakeMutationService())
    monkeypatch.setattr(routes_module, "get_config", lambda: fake_config)
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: FakeMetadataService())
    monkeypatch.setattr("app.core.rename_service.RenameService", lambda: FakeRenameService())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)
    monkeypatch.setattr("app.core.activity_log_service.log_batch_api_rename_result", lambda **_kwargs: None)

    response = asyncio.run(routes_module.batch_api_rename_library_items(
        _FakeJsonRequest(
            {"library_id": library.id, "paths": [str(first), str(second)]},
            headers={"Idempotency-Key": "batch-api-rename-key"},
        ),
        None,
    ))

    assert response["operation_state"] == "committed"
    assert response["success_count"] == 1
    assert response["failed_count"] == 1
    assert captured["filesystem_started"] == "batch-api-rename-operation"
    assert captured["prepare"]["idempotency_key"] == "batch-api-rename-key"
    assert captured["batch_rename"]["skip_index_mutation"] is True
    assert captured["batch_rename"]["sync_index_mutation"] is False
    effects = captured["finalize"]["actual_effects_by_library"][library.id]
    assert len(effects) == 2
    assert effects[0]["relative_path"] == first.name
    assert effects[0]["kind"] == "move"
    assert effects[1]["kind"] == "reconcile"
    assert all(second.name not in str(effect) for effect in effects)


def test_index_replace_many_records_one_ledger_envelope(monkeypatch):
    manager = object.__new__(library_manager_module.LibraryManager)
    library = library_manager_module.LibraryDefinition(
        id="local-library",
        name="本地库存",
        type="local",
        path="/library",
    )
    captured = {}

    class FakeMutationService:
        def prepare(self, **kwargs):
            captured["prepare"] = kwargs
            return SimpleNamespace(operation_id="replace-operation")

        def mark_filesystem_started(self, operation_id):
            captured["filesystem_started"] = operation_id

        def finalize(self, operation_id, **kwargs):
            captured["finalize"] = {"operation_id": operation_id, **kwargs}
            return kwargs["actual_result"]

    monkeypatch.setattr(library_index_module, "get_library_index_mutation_service", lambda: FakeMutationService())

    assert manager._enqueue_index_replace_subtree_many(
        library,
        [f"/library/work-{index}" for index in range(200)],
    ) is True

    effects = captured["prepare"]["effects_by_library"]["local-library"]
    assert len(effects) == 200
    assert all(effect["kind"] == "reconcile" for effect in effects)
    assert captured["filesystem_started"] == "replace-operation"
    assert captured["finalize"]["actual_result"]["path_count"] == 200
