from pathlib import Path

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
