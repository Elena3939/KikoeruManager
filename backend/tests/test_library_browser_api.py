from pathlib import Path

from app.core import library_manager as library_manager_module


class _LegacyStorage:
    def __init__(self, library_path: str):
        self.library_path = library_path


class _LegacyConfig:
    def __init__(self, library_path: str):
        self.storage = _LegacyStorage(library_path)


def test_library_browser_endpoints_support_multi_library(client, monkeypatch, tmp_path):
    local_root = tmp_path / "library-a"
    nested_root = local_root / "RJ000001"
    target_dir = nested_root / "[RJ000001] Demo"
    target_dir.mkdir(parents=True)
    (target_dir / "track.wav").write_bytes(b"demo-data")

    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """
storage:
  library_path: "%s"
  libraries:
    - id: local-a
      name: 本地 A
      type: local
      path: "%s"
      enabled: true
  default_library_id: local-a
  default_extract_library_id: local-a
  health_warning_free_gb: 1
  stats_cache_ttl_seconds: 1
"""
        % (str(local_root).replace("\\", "\\\\"), str(local_root).replace("\\", "\\\\")),
        encoding="utf-8",
    )

    monkeypatch.setattr(library_manager_module, "_config_file_path", lambda: str(config_yaml))
    monkeypatch.setattr(library_manager_module, "get_config", lambda: _LegacyConfig(str(local_root)))

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
