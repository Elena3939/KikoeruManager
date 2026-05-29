import pytest

from app.core.http_download_service import (
    HttpDownloadError,
    HttpDownloadService,
    sanitize_http_download_error,
    sanitize_http_download_metadata,
    sanitize_http_download_preview,
)
from app.config.settings import HttpDownloaderConfig


class DummyStorage:
    temp_path = ""


class DummyHttpDownloader:
    enabled = True
    engine = "aria2"
    download_root = ""
    aria2_path = "aria2c"
    proxy_url = ""
    max_concurrent_downloads = 3
    split = 8
    max_connection_per_server = 8
    min_split_size = "1M"
    retry_count = 5
    retry_wait_seconds = 5
    connect_timeout_seconds = 15
    timeout_seconds = 60
    allow_private_network = False
    conflict_policy = "resume"
    pikpak_enabled = False
    pikpak_username = ""
    pikpak_password = ""
    pikpak_encoded_token = ""
    pikpak_device_id = ""
    pikpak_transfer_dir = "/KikoeruManager"
    pikpak_auto_save_share = True


class DummyConfig:
    def __init__(self, tmp_path):
        self.storage = DummyStorage()
        self.storage.temp_path = str(tmp_path / "temp")
        self.http_downloader = DummyHttpDownloader()
        self.http_downloader.download_root = str(tmp_path / "downloads")


def bind_config(monkeypatch, tmp_path, **overrides):
    cfg = DummyConfig(tmp_path)
    for key, value in overrides.items():
        setattr(cfg.http_downloader, key, value)
    monkeypatch.setattr("app.core.http_download_service.get_config", lambda: cfg)
    return cfg


@pytest.mark.asyncio
async def test_validate_url_rejects_non_http(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    with pytest.raises(HttpDownloadError, match="仅支持"):
        await service.validate_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_validate_url_blocks_private_network_by_default(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    with pytest.raises(HttpDownloadError, match="内网"):
        await service.validate_url("http://127.0.0.1/file.zip")


@pytest.mark.asyncio
async def test_validate_url_allows_private_network_when_enabled(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, allow_private_network=True)
    service = HttpDownloadService()

    assert await service.validate_url("http://127.0.0.1/file.zip") == "http://127.0.0.1/file.zip"


@pytest.mark.asyncio
async def test_validate_url_blocks_dns_rebinding_to_private_ip(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_host_ips(_host):
        return ["10.0.0.8"]

    monkeypatch.setattr(service, "_resolve_host_ips", fake_resolve_host_ips)

    with pytest.raises(HttpDownloadError, match="内网"):
        await service.validate_url("https://example.test/file.zip")


def test_safe_subdir_rejects_parent_traversal(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    with pytest.raises(HttpDownloadError, match="上级路径"):
        service._resolve_target("file.zip", "../escape", "resume")


def test_resolve_target_stays_under_download_root(monkeypatch, tmp_path):
    cfg = bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    target = service._resolve_target("a<>b?.zip", "gofile/RJ123456", "resume")

    assert target["filename"] == "a__b_.zip"
    assert target["relative_path"] == "gofile/RJ123456/a__b_.zip"
    assert target["final_path"].startswith(cfg.http_downloader.download_root)


def test_resolve_target_rename_avoids_existing_file(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    existing = tmp_path / "downloads" / "file.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")

    target = service._resolve_target("file.zip", "", "rename")

    assert target["filename"] == "file (1).zip"


def test_resolve_target_skip_rejects_existing_file(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    existing = tmp_path / "downloads" / "file.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")

    with pytest.raises(HttpDownloadError, match="已存在"):
        service._resolve_target("file.zip", "", "skip")


def test_content_range_preview_size(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._content_length_from_headers({"content-range": "bytes 0-0/2048", "content-length": "1"}) == 2048


def test_mask_url_hides_credentials(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._mask_url("https://user:secret@example.com/file.zip?token=abc") == "https://***:***@example.com/file.zip?query=***"
    assert service._mask_url("https://example.com/file.zip?token=abc") == "https://example.com/file.zip?query=***"


def test_sanitize_preview_masks_url_and_removes_original_url():
    preview = {
        "items": [
            {
                "ok": True,
                "url": "https://user:secret@example.com/file.zip?token=abc",
                "original_url": "https://user:secret@example.com/file.zip?token=abc",
            },
        ],
    }

    sanitized = sanitize_http_download_preview(preview)

    assert sanitized["items"][0]["url"] == "https://***:***@example.com/file.zip?query=***"
    assert sanitized["items"][0]["masked_url"] == "https://***:***@example.com/file.zip?query=***"
    assert "original_url" not in sanitized["items"][0]


def test_sanitize_metadata_removes_retry_urls_but_keeps_public_file_rows():
    metadata = {
        "urls": ["https://user:secret@example.com/a.zip"],
        "resolved_urls": ["https://cdn.example.com/a.zip?token=abc"],
        "download_files": [
            {
                "name": "a.zip",
                "url": "https://***:***@example.com/a.zip",
                "original_url": "https://user:secret@example.com/a.zip",
            },
        ],
        "failed_files": [
            {
                "url": "https://user:secret@example.com/b.zip",
                "original_url": "https://user:secret@example.com/b.zip",
            },
        ],
        "preview_items": [
            {"url": "https://user:secret@example.com/c.zip"},
        ],
        "source_items": [
            {"source": "pikpak", "url": "https://cdn.example.com/d.zip?token=abc", "original_url": "https://cdn.example.com/d.zip?token=abc"},
        ],
    }

    sanitized = sanitize_http_download_metadata(metadata)

    assert "urls" not in sanitized
    assert "resolved_urls" not in sanitized
    assert "original_url" not in sanitized["download_files"][0]
    assert sanitized["download_files"][0]["url"] == "https://***:***@example.com/a.zip"
    assert sanitized["failed_files"][0]["url"] == "https://***:***@example.com/b.zip"
    assert sanitized["preview_items"][0]["url"] == "https://***:***@example.com/c.zip"
    assert "original_url" not in sanitized["source_items"][0]
    assert sanitized["source_items"][0]["url"] == "https://cdn.example.com/d.zip?query=***"


def test_sanitize_preview_drops_resolved_urls_and_masks_source_items():
    preview = {
        "resolved_urls": ["https://cdn.example.com/a.zip?token=secret"],
        "source_items": [
            {"source": "pikpak", "url": "https://cdn.example.com/a.zip?token=secret", "original_url": "https://cdn.example.com/a.zip?token=secret"},
        ],
        "items": [],
    }

    sanitized = sanitize_http_download_preview(preview)

    assert "resolved_urls" not in sanitized
    assert "original_url" not in sanitized["source_items"][0]
    assert sanitized["source_items"][0]["url"] == "https://cdn.example.com/a.zip?query=***"


def test_sanitize_error_masks_url_credentials_and_tokens():
    message = "Cannot connect to http://user:secret@127.0.0.1:7890 via https://example.com/file.zip?token=abc"

    sanitized = sanitize_http_download_error(message)

    assert "secret" not in sanitized
    assert "token=abc" not in sanitized
    assert "http://***:***@127.0.0.1:7890" in sanitized
    assert "https://example.com/file.zip?query=***" in sanitized


def test_proxy_url_normalizes_scheme(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, proxy_url="127.0.0.1:7890")
    service = HttpDownloadService()

    assert service._proxy_url() == "http://127.0.0.1:7890"


def test_http_downloader_config_has_pikpak_defaults():
    cfg = HttpDownloaderConfig()

    assert cfg.pikpak_enabled is False
    assert cfg.pikpak_transfer_dir == "/KikoeruManager"
    assert cfg.pikpak_auto_save_share is True


def test_pikpak_url_detection(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._is_pikpak_url("https://mypikpak.com/s/abc123")
    assert service._is_pikpak_url("https://drive.mypikpak.com/s/abc123")
    assert not service._is_pikpak_url("https://example.com/s/abc123")


def test_pikpak_pass_code_from_query_and_fragment(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._parse_pikpak_pass_code("https://mypikpak.com/s/abc?pwd=9z8y") == "9z8y"
    assert service._parse_pikpak_pass_code("https://mypikpak.com/s/abc#提取码:abcd") == "abcd"


@pytest.mark.asyncio
async def test_collect_pikpak_share_files_walks_folder(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def get_share_info(self, share_link, pass_code=None):
            return {
                "share_id": "share-id",
                "pass_code_token": "token",
                "files": [
                    {"id": "folder-1", "name": "folder", "kind": "drive#folder"},
                    {"id": "file-1", "name": "root.zip", "kind": "drive#file"},
                ],
            }

        async def get_share_folder(self, share_id, pass_code_token, parent_id=None):
            assert share_id == "share-id"
            assert pass_code_token == "token"
            assert parent_id == "folder-1"
            return {"files": [{"id": "file-2", "name": "child.zip", "kind": "drive#file"}]}

    _info, files = await service._collect_pikpak_share_files(Client(), "https://mypikpak.com/s/share-id")

    assert [item["id"] for item in files] == ["file-2", "file-1"]
    assert files[0]["_relative_dir"] == "folder"


@pytest.mark.asyncio
async def test_copy_pikpak_share_files_maps_copied_ids(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def path_to_id(self, path, create=False):
            assert path == "/KikoeruManager"
            assert create is True
            return [{"id": "target-folder"}]

        async def file_batch_copy(self, ids, to_parent_id=None):
            assert ids == ["src-1"]
            assert to_parent_id == "target-folder"
            return {"files": [{"original_file_id": "src-1", "id": "copied-1"}]}

    id_map = await service._copy_pikpak_share_files(Client(), ["src-1"])

    assert id_map["src-1"] == "copied-1"


@pytest.mark.asyncio
async def test_resolve_source_urls_rejects_pikpak_when_not_configured(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, pikpak_enabled=True, pikpak_username="", pikpak_password="", pikpak_encoded_token="")
    service = HttpDownloadService()

    with pytest.raises(HttpDownloadError, match="PikPak 未配置"):
        await service.resolve_source_urls(["https://mypikpak.com/s/share-id"])


@pytest.mark.asyncio
async def test_preview_urls_uses_resolved_pikpak_urls(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://cdn.example.com/a.zip?token=secret"],
            "source_items": [{"source": "pikpak", "url": "https://cdn.example.com/a.zip?token=secret"}],
            "failed_items": [],
            "source_modes": ["pikpak"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy=""):
        return {
            "ok": True,
            "url": raw_url,
            "masked_url": service._mask_url(raw_url),
            "host": "cdn.example.com",
            "filename": "a.zip",
            "relative_path": "a.zip",
            "final_path": str(tmp_path / "downloads" / "a.zip"),
            "target_dir": str(tmp_path / "downloads"),
            "size_bytes": 10,
            "resumable": True,
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)

    preview = await service.preview_urls(["https://mypikpak.com/s/share-id"])
    public_preview = sanitize_http_download_preview(preview)

    assert preview["resolved_urls"] == ["https://cdn.example.com/a.zip?token=secret"]
    assert preview["source_modes"] == ["pikpak"]
    assert "resolved_urls" not in public_preview
    assert public_preview["items"][0]["url"] == "https://cdn.example.com/a.zip?query=***"


@pytest.mark.asyncio
async def test_preview_urls_shows_pikpak_share_without_materializing(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        assert materialize is False
        return {
            "urls": [],
            "source_items": [
                {
                    "source": "pikpak",
                    "share_url": "https://mypikpak.com/s/share-id",
                    "url": "https://mypikpak.com/s/share-id",
                    "filename": "voice.zip",
                    "size_bytes": 12,
                    "preview_only": True,
                }
            ],
            "failed_items": [],
            "source_modes": ["pikpak"],
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)

    preview = await service.preview_urls(["https://mypikpak.com/s/share-id"], target_subdir="pikpak")

    assert preview["ok_count"] == 1
    assert preview["needs_materialize"] is True
    assert preview["items"][0]["source"] == "pikpak"
    assert preview["items"][0]["relative_path"] == "pikpak/voice.zip"


@pytest.mark.asyncio
async def test_poll_task_aggregates_rpc_status(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_tell_status(gid):
        return {
            "gid": gid,
            "status": "active" if gid == "a" else "complete",
            "totalLength": "100",
            "completedLength": "40" if gid == "a" else "100",
            "downloadSpeed": "12" if gid == "a" else "0",
        }

    monkeypatch.setattr(service, "_tell_status", fake_tell_status)
    rows = [
        {"gid": "a", "name": "a.bin", "relative_path": "a.bin"},
        {"gid": "b", "name": "b.bin", "relative_path": "b.bin"},
    ]

    next_rows, runtime, done, failed = await service._poll_task(["a", "b"], rows)

    assert done is False
    assert failed == 0
    assert runtime["completed_files"] == 1
    assert runtime["active_file_count"] == 1
    assert runtime["transferred_bytes"] == 140
    assert runtime["speed_bytes_per_sec"] == 12
    assert next_rows[0]["progress"] == 40
    assert next_rows[1]["status"] == "completed"


@pytest.mark.asyncio
async def test_pause_resume_cancel_call_rpc_for_known_gids(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    service._task_gids["task-1"] = ["gid-1", "gid-2"]
    calls = []

    async def fake_rpc(method, params):
        calls.append((method, params))

    monkeypatch.setattr(service, "_rpc_call", fake_rpc)

    await service.pause_task("task-1")
    await service.resume_task("task-1")
    await service.cancel_task("task-1")

    assert ("aria2.pause", ["gid-1"]) in calls
    assert ("aria2.unpause", ["gid-1"]) in calls
    assert ("aria2.remove", ["gid-1"]) in calls
    assert "task-1" not in service._task_gids
