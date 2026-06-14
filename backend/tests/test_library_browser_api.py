import os
from pathlib import Path

from app.api import routes as routes_module
from app.config.settings import LibraryConfigItem, StorageConfig
from app.core import library_manager as library_manager_module


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
