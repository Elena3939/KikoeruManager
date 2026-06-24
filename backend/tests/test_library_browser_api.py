import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import routes as routes_module
from app.config.settings import LibraryConfigItem, StorageConfig
from app.core import library_index as library_index_module
from app.core import library_folder_completion_service as folder_completion_module
from app.core import library_manager as library_manager_module
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
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


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

    manager = object.__new__(library_manager_module.LibraryManager)
    manager._size_cache = {}
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: FakeIndexService())

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
    assert [item["name"] for item in indexed_list_result["files"]] == ["old-track.mp3", "subtitles"]

    result = asyncio.run(manager.folder_contents(library.id, str(circle_dir), recursive=False))

    assert result.get("browse_via_index") is True
    assert result["total_files"] == 3
    rj_item = next(item for item in result["items"] if item["name"] == "RJ01000001")
    assert rj_item["size"] == 9
    assert rj_item["size_status"] == "stale"
    assert rj_item["index_refresh_pending"] is True
    assert rj_item["file_count"] == 2
    assert rj_item["folder_count"] is None
    assert rj_item["folder_count_status"] == "lazy"

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
    assert folders_payload.get("browse_via_index") is not True
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
    submitted_moves = []
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

    class FakeIndexService:
        def is_ready(self, library_id):
            return library_id == "local-a"

        def handle_self_mutation_move_many(self, moves):
            submitted_moves.extend(moves)
            return [1 for _ in moves]

    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: FakeIndexService())
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
    assert submitted_moves == [{
        "source_library_id": "local-a",
        "target_library_id": "local-a",
        "old_relative_path": "RJ01000001/old.wav",
        "new_relative_path": "RJ01000001/new.wav",
        "old_absolute_path": str(work_dir / "old.wav"),
        "new_absolute_path": str(work_dir / "new.wav"),
    }]


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


def test_library_browser_rename_syncs_index_by_default(monkeypatch):
    captured = {}

    class FakeLibraryManager:
        async def rename(self, library_id, path, new_name, *, skip_index_mutation=False, sync_index_mutation=False):
            captured["library_id"] = library_id
            captured["path"] = path
            captured["new_name"] = new_name
            captured["skip_index_mutation"] = skip_index_mutation
            captured["sync_index_mutation"] = sync_index_mutation
            return {"message": "重命名成功", "new_path": path.replace("old", "new")}

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.rename_library_browser_item(_FakeJsonRequest({
            "library_id": "local-a",
            "path": "/library/work/old",
            "new_name": "new",
            "skip_activity_log": True,
        }))
    )

    assert response["new_path"] == "/library/work/new"
    assert captured["skip_index_mutation"] is False
    assert captured["sync_index_mutation"] is True


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

    monkeypatch.setattr(routes_module, "get_library_manager", lambda: FakeLibraryManager())
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)
    monkeypatch.setattr("app.core.activity_log_service.log_batch_manual_rename_result", lambda **_kwargs: None)

    response = asyncio.run(
        routes_module.batch_rename_library_browser_items(_FakeJsonRequest({
            "library_id": "local-a",
            "items": [{"path": "/library/work/old", "new_name": "new", "current_name": "old"}],
            "skip_activity_log": True,
        }))
    )

    assert response["success_count"] == 1
    assert captured["skip_index_mutation"] is False
    assert captured["sync_index_mutation"] is True


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

    with pytest.raises(routes_module.HTTPException) as exc_info:
        asyncio.run(
            routes_module.api_rename_library_file(_FakeJsonRequest({
                "library_id": "remote-a",
                "path": "/library_amsr/青春/RJ01572763",
            }))
        )

    assert exc_info.value.status_code == 422
    assert "DLsite 元数据不可用" in str(exc_info.value.detail)
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
    with pytest.raises(routes_module.HTTPException) as exc_info:
        asyncio.run(
            routes_module.api_rename_library_file(_FakeJsonRequest({
                "library_id": "remote-a",
                "path": markdown_path,
            }))
        )

    assert exc_info.value.status_code == 422
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
    assert captured["metadata_task_rjcode"] == "RJ01572763"
    assert captured["metadata_task_metadata"] == {
        "rjcode": "RJ01572763",
        "rjcode_lock": True,
    }
    assert "batch_rename_called" not in captured


def test_index_mutation_threshold_schedules_background_flush(monkeypatch):
    manager = object.__new__(library_manager_module.LibraryManager)
    manager._index_mutation_lock = threading.Lock()
    manager._index_mutation_timer = None
    manager._index_mutation_pending_deletes = {}
    manager._index_mutation_pending_upserts = {}
    manager._index_mutation_pending_replaces = {}
    manager._index_mutation_pending_moves = {}

    library = SimpleNamespace(id="local-library", type="local")
    scheduled = []

    def fake_schedule(*, delay_seconds=0.1):
        scheduled.append(delay_seconds)

    def fail_sync_flush():
        raise AssertionError("索引队列达到阈值也不应在业务线程同步 flush")

    monkeypatch.setattr(manager, "_normalize_index_abs_key", lambda _library, path: path)
    monkeypatch.setattr(manager, "_schedule_index_mutation_flush_locked", fake_schedule)
    monkeypatch.setattr(manager, "_flush_index_mutations", fail_sync_flush)

    assert manager._enqueue_index_replace_subtree_many(
        library,
        [f"/library/work-{index}" for index in range(200)],
    ) is True

    assert scheduled == [0]
