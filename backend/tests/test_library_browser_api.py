import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

from app.api import routes as routes_module
from app.config.settings import LibraryConfigItem, StorageConfig
from app.core import library_index as library_index_module
from app.core import library_folder_completion_service as folder_completion_module
from app.core import library_manager as library_manager_module
from app.core.library_index.types import IndexEntry


class _RuntimeConfig:
    """让 ``get_config().storage`` 返回真实的 StorageConfig（带多库存条目）。

    生产 ``load_library_config()`` 直接调 ``get_config().storage.model_dump()``，
    完全不读 yaml；原测试 monkeypatch 的 ``_config_file_path`` 路径根本未被使用。
    本测试改为直接构造一份多库存 StorageConfig，覆盖 get_config 即可。
    """

    def __init__(self, storage: StorageConfig):
        self.storage = storage


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

    stats_response = client.get("/api/library/browser/stats", params={"force_refresh": "true"})
    assert stats_response.status_code == 200
    assert "all_libraries" in stats_response.json()


def test_folder_contents_shallow_uses_ready_index_directory_stats(monkeypatch, tmp_path):
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
            entry("Circle/RJ01000001/track.mp3", "file", 5, 0),
            entry("Circle/RJ01000001/subtitles/track.vtt", "file", 4, 0),
            entry("Circle/cover.jpg", "file", 3, 0),
        ]
    }

    class FakeIndexService:
        def is_ready(self, library_id):
            return library_id == library.id

        def get_entry(self, library_id, relative_path):
            return entries.get(relative_path)

        def list_children_page(self, library_id, parent_path="", **_kwargs):
            return {
                "entries": [
                    item
                    for item in entries.values()
                    if (item.parent_path or "") == (parent_path or "")
                ],
                "total": 0,
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

    manager = object.__new__(library_manager_module.LibraryManager)
    monkeypatch.setattr(manager, "get_library_definition", lambda _library_id: library)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(library_index_module, "get_library_index_service", lambda: FakeIndexService())

    result = asyncio.run(manager.folder_contents(library.id, str(circle_dir), recursive=False))

    assert result["browse_via_index"] is True
    assert result["total_size"] == 12
    assert result["total_files"] == 3
    assert result["total_folder_count"] == 2
    rj_item = next(item for item in result["items"] if item["name"] == "RJ01000001")
    assert rj_item["size"] == 9
    assert rj_item["size_status"] == "ready"
    assert rj_item["file_count"] == 2
    assert rj_item["folder_count"] == 1

    recursive_result = asyncio.run(manager.folder_contents(library.id, str(circle_dir), recursive=True))
    assert recursive_result["browse_via_index"] is True
    assert recursive_result["recursive"] is True
    assert recursive_result["total_files"] == 3
    assert [item["relative_path"] for item in recursive_result["items"]] == [
        "RJ01000001/subtitles/track.vtt",
        "RJ01000001/track.mp3",
        "cover.jpg",
    ]

    folders_payload = asyncio.run(manager.list_local_folders_only(library.id, str(circle_dir), include_files=True))
    assert folders_payload["browse_via_index"] is True
    folder_row = next(item for item in folders_payload["folders"] if item["name"] == "RJ01000001")
    assert folder_row["size"] == 9
    assert folder_row["file_count"] == 2
    assert folder_row["folder_count"] == 1

    completion_service = object.__new__(folder_completion_module.LibraryFolderCompletionService)
    completion_service.manager = manager
    completion_targets, completion_skipped = completion_service._resolve_selected_path_targets(library, str(circle_dir))
    assert completion_skipped == []
    assert [target.folder_path for target in completion_targets] == [str(rj_dir)]

    delete_preview = manager._local_delete(library, str(rj_dir), confirmed=False)
    assert delete_preview["browse_via_index"] is True
    assert delete_preview["size"] == 9
    assert delete_preview["file_count"] == 2
    assert delete_preview["folder_count"] == 2

    batch_preview = manager._local_batch_delete(library, [str(rj_dir), str(circle_dir / "cover.jpg")], confirmed=False)
    assert batch_preview["browse_via_index"] is True
    assert batch_preview["total_size"] == 12
    assert batch_preview["total_file_count"] == 3
    assert batch_preview["total_folder_count"] == 2

    filter_preview = manager._local_filter_delete_preview(
        library,
        str(circle_dir),
        [{"name": "删 RJ 目录", "pattern": "RJ01000001", "target": "folder", "enabled": True}],
    )
    assert filter_preview["browse_via_index"] is True
    assert filter_preview["selected_count"] == 1
    assert filter_preview["selected_size"] == 9
    assert [item["relative_path"] for item in filter_preview["items"]] == [
        "RJ01000001",
        "RJ01000001/subtitles",
        "RJ01000001/track.mp3",
        "RJ01000001/subtitles/track.vtt",
    ]


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
    monkeypatch.setattr(
        manager,
        "_notify_index_self_mutation_move_batch",
        lambda _source_library, _target_library, items: moved_items.extend(items),
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
        lambda _source_library, _target_library, items: moved_items.extend(items),
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


def test_subtitle_manual_match_batch_rename_skips_index_mutation(client, monkeypatch):
    captured = {}

    class FakeLibraryManager:
        async def batch_rename(self, library_id, items, *, skip_index_mutation=False):
            captured["library_id"] = library_id
            captured["items"] = items
            captured["skip_index_mutation"] = skip_index_mutation
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

    response = client.post(
        "/api/library/browser/batch-rename",
        json={
            "library_id": "local-a",
            "items": [{"path": "/library/workbench/old.vtt", "new_name": "new.vtt"}],
            "skip_activity_log": True,
            "rename_context": "subtitle_manual_match_pair",
        },
    )

    assert response.status_code == 200
    assert captured["library_id"] == "local-a"
    assert captured["skip_index_mutation"] is True


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
