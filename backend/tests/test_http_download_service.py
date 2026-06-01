import asyncio

import pytest
from pathlib import Path

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


class DummyMetadata:
    http_proxy = None


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
    gofile_token = ""
    pikpak_enabled = False
    pikpak_username = ""
    pikpak_password = ""
    pikpak_encoded_token = ""
    pikpak_device_id = ""
    pikpak_transfer_dir = "/KikoeruManager"
    pikpak_auto_save_share = True
    pikpak_accounts = []


class DummyConfig:
    def __init__(self, tmp_path):
        self.storage = DummyStorage()
        self.storage.temp_path = str(tmp_path / "temp")
        self.metadata = DummyMetadata()
        self.http_downloader = DummyHttpDownloader()
        self.http_downloader.download_root = str(tmp_path / "downloads")


def bind_config(monkeypatch, tmp_path, **overrides):
    cfg = DummyConfig(tmp_path)
    for key, value in overrides.items():
        if key.startswith("metadata_"):
            setattr(cfg.metadata, key.removeprefix("metadata_"), value)
        else:
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


def test_download_root_defaults_to_storage_input_path(monkeypatch, tmp_path):
    cfg = bind_config(monkeypatch, tmp_path, download_root="")
    cfg.storage.input_path = str(tmp_path / "input")
    service = HttpDownloadService()

    assert service._download_root() == str(tmp_path / "input")


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


def test_proxy_url_falls_back_to_metadata_proxy(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, proxy_url="", metadata_http_proxy="127.0.0.1:7890")
    service = HttpDownloadService()

    assert service._proxy_url() == "http://127.0.0.1:7890"


def test_proxy_url_prefers_http_downloader_proxy(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        proxy_url="http://127.0.0.1:7891",
        metadata_http_proxy="127.0.0.1:7890",
    )
    service = HttpDownloadService()

    assert service._proxy_url() == "http://127.0.0.1:7891"


@pytest.mark.asyncio
async def test_preview_url_passes_provider_headers(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, allow_private_network=True)
    service = HttpDownloadService()
    seen_headers = []

    class FakeResponse:
        status = 200
        url = "https://cdn.example.test/file.zip"
        headers = {
            "Content-Length": "12",
            "Accept-Ranges": "bytes",
            "Content-Disposition": 'attachment; filename="file.zip"',
        }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def head(self, _url, allow_redirects=True, headers=None, proxy=None):
            seen_headers.append(dict(headers or {}))
            return FakeResponse()

    async def fake_resolve_host_ips(_host):
        return ["93.184.216.34"]

    monkeypatch.setattr("app.core.http_download_service.aiohttp.ClientSession", FakeSession)
    monkeypatch.setattr(service, "_resolve_host_ips", fake_resolve_host_ips)

    preview = await service.preview_url(
        "https://cdn.example.test/file.zip",
        headers={"Cookie": "accountToken=secret-token"},
    )

    assert preview["ok"] is True
    assert seen_headers == [{"Cookie": "accountToken=secret-token"}]


def test_http_downloader_config_has_pikpak_defaults():
    cfg = HttpDownloaderConfig()

    assert cfg.gofile_token == ""
    assert cfg.pikpak_enabled is False
    assert cfg.pikpak_transfer_dir == "/KikoeruManager"
    assert cfg.pikpak_auto_save_share is True


def test_pikpak_url_detection(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._is_pikpak_url("https://mypikpak.com/s/abc123")
    assert service._is_pikpak_url("https://drive.mypikpak.com/s/abc123")
    assert not service._is_pikpak_url("https://example.com/s/abc123")


def test_share_provider_url_detection(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._provider_source("https://gofile.io/d/abc123") == "gofile"
    assert service._provider_source("https://transfer.it/t/iVqeTDhlyRbA") == "transferit"
    assert service._provider_source("https://1drv.ms/u/s!abc") == "onedrive"
    assert service._provider_source("https://drive.google.com/file/d/file-id/view?usp=sharing") == "google_drive"
    assert service._provider_source("https://example.com/file.zip") == "http"


def test_google_drive_direct_url_from_share_link(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._google_drive_direct_url("https://drive.google.com/file/d/file-id/view?usp=sharing") == "https://drive.usercontent.google.com/download?id=file-id&export=download"
    assert service._google_drive_direct_url("https://drive.google.com/open?id=file-id") == "https://drive.usercontent.google.com/download?id=file-id&export=download"


def test_google_drive_folder_id_from_share_link(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    folder_url = "https://drive.google.com/drive/folders/1Mq4yNPHMFlA7foAXjuCs_3DU-oN5ROim?usp=sharing"

    assert service._google_drive_folder_id_from_url(folder_url) == "1Mq4yNPHMFlA7foAXjuCs_3DU-oN5ROim"
    assert service._google_drive_is_folder_url(folder_url) is True
    assert service._google_drive_is_folder_url("https://drive.google.com/file/d/file-id/view") is False


def test_google_drive_confirm_url_from_warning_html(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    html = """
    <form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
      <input type="hidden" name="id" value="file-id">
      <input type="hidden" name="export" value="download">
      <input type="hidden" name="confirm" value="t">
      <input type="hidden" name="uuid" value="uuid-token">
    </form>
    <span class="uc-name-size"><a href="/open?id=file-id">RJ01603546.zip</a> (1.5G)</span>
    """

    url = service._google_drive_confirm_url_from_warning_html(
        html,
        "https://drive.usercontent.google.com/download?id=file-id&export=download",
    )

    assert url == "https://drive.usercontent.google.com/download?id=file-id&export=download&confirm=t&uuid=uuid-token"
    assert service._google_drive_size_from_warning_html(html) == int(1.5 * 1024 * 1024 * 1024)


def test_onedrive_direct_url_adds_download_param(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._onedrive_direct_url("https://1drv.ms/u/s!abc?e=token") == "https://1drv.ms/u/s!abc?e=token&download=1"


def test_pikpak_pass_code_from_query_and_fragment(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    assert service._parse_pikpak_pass_code("https://mypikpak.com/s/abc?pwd=9z8y") == "9z8y"
    assert service._parse_pikpak_pass_code("https://mypikpak.com/s/abc#提取码:abcd") == "abcd"
    assert service._parse_pikpak_pass_code("https://mypikpak.com/s/abc 提取码：A1b2") == "A1b2"
    assert service._pikpak_share_url("https://mypikpak.com/s/abc 提取码：A1b2") == "https://mypikpak.com/s/abc"


def test_pikpak_accounts_include_legacy_and_extra_accounts(monkeypatch, tmp_path):
    cfg = bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_username="legacy@example.com",
        pikpak_password="legacy-pass",
        pikpak_accounts=[
            {
                "id": "second",
                "label": "二号",
                "enabled": True,
                "username": "second@example.com",
                "password": "pass",
                "encoded_token": "",
                "device_id": "dev-2",
                "transfer_dir": "/KikoeruManager-B",
            },
            {
                "id": "disabled",
                "enabled": False,
                "username": "disabled@example.com",
                "password": "pass",
            },
        ],
    )
    service = HttpDownloadService()

    accounts = service._pikpak_accounts()

    assert [item.id for item in accounts] == ["default", "second"]
    assert accounts[0].legacy is True
    assert accounts[1].transfer_dir == "/KikoeruManager-B"
    assert service._select_pikpak_account("second").username == "second@example.com"
    assert cfg.http_downloader.pikpak_accounts[0]["id"] == "second"


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
async def test_collect_pikpak_share_files_reports_region_prohibited(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def get_share_info(self, share_link, pass_code=None):
            return {
                "share_status": "PROHIBITED",
                "share_status_text": "Sorry, sharing is not available in the current region",
                "files": [],
            }

    with pytest.raises(HttpDownloadError, match="地区不可用|当前账号/地区不可用"):
        await service._collect_pikpak_share_files(Client(), "https://mypikpak.com/s/share-id")


@pytest.mark.asyncio
async def test_copy_pikpak_share_files_maps_copied_ids(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def path_to_id(self, path, create=False):
            assert path == "/KikoeruManager"
            assert create is True
            return [{"id": "target-folder"}]

        async def restore(self, share_id, pass_code_token, file_ids, parent_id=None):
            assert share_id == "share-id"
            assert pass_code_token == "token"
            assert file_ids == ["src-1"]
            assert parent_id == "target-folder"
            return {"files": [{"original_file_id": "src-1", "id": "copied-1"}]}

    id_map = await service._copy_pikpak_share_files(Client(), ["src-1"], share_id="share-id", pass_code_token="token")

    assert id_map["src-1"] == "copied-1"


@pytest.mark.asyncio
async def test_copy_pikpak_share_files_reports_space_shortage(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def path_to_id(self, path, create=False):
            return [{"id": "target-folder"}]

        async def get_quota_info(self):
            return {"quota": {"limit": "100", "usage": "90", "usage_in_trash": "0"}}

        async def restore(self, share_id, pass_code_token, file_ids, parent_id=None):
            raise AssertionError("空间不足时不应该继续转存")

    with pytest.raises(HttpDownloadError, match="转存空间不足"):
        await service._copy_pikpak_share_files(Client(), ["src-1"], [{"id": "src-1", "size": 20}], share_id="share-id", pass_code_token="token")


@pytest.mark.asyncio
async def test_copy_pikpak_share_files_multi_splits_by_remaining_space(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[
            {"id": "small", "label": "小号", "enabled": True, "username": "small", "password": "p", "transfer_dir": "/Small"},
            {"id": "large", "label": "大号", "enabled": True, "username": "large", "password": "p", "transfer_dir": "/Large"},
        ],
    )
    service = HttpDownloadService()
    copied = {}

    class Client:
        def __init__(self, account_id, quota_remaining):
            self._kikoeru_pikpak_account = service._select_pikpak_account(account_id)
            self.quota_remaining = quota_remaining

        async def get_quota_info(self):
            return {"quota": {"limit": "100", "usage": str(100 - self.quota_remaining), "usage_in_trash": "0"}}

        async def get_share_info(self, share_link, pass_code=None):
            return {"share_id": "share-id", "pass_code_token": "token", "files": []}

        async def path_to_id(self, path, create=False):
            return [{"id": f"folder-{self._kikoeru_pikpak_account.id}"}]

        async def restore(self, share_id, pass_code_token, file_ids, parent_id=None):
            assert share_id == "share-id"
            assert pass_code_token == "token"
            assert parent_id == f"folder-{self._kikoeru_pikpak_account.id}"
            copied[self._kikoeru_pikpak_account.id] = list(file_ids)
            return {"files": [{"original_file_id": item, "id": f"{self._kikoeru_pikpak_account.id}-{item}"} for item in file_ids]}

    clients = {
        "small": Client("small", 60),
        "large": Client("large", 100),
    }

    async def fake_client(account_id="", *, account=None):
        return clients[(account.id if account else account_id) or "small"]

    monkeypatch.setattr(service, "_pikpak_client", fake_client)
    monkeypatch.setattr(service, "_close_pikpak_client", lambda _client: asyncio.sleep(0))

    id_map, account_by_source = await service._copy_pikpak_share_files_multi(
        clients["small"],
        ["big", "mid"],
        [{"id": "big", "size": 90}, {"id": "mid", "size": 50}],
        share_link="https://mypikpak.com/s/share-id",
        share_id="share-id",
        pass_code_token="token",
    )

    assert copied["large"] == ["big"]
    assert copied["small"] == ["mid"]
    assert id_map["big"] == "large-big"
    assert id_map["mid"] == "small-mid"
    assert account_by_source["big"].id == "large"
    assert account_by_source["mid"].id == "small"


@pytest.mark.asyncio
async def test_copy_pikpak_share_files_multi_reports_combined_space_shortage(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[
            {"id": "a", "label": "A", "enabled": True, "username": "a", "password": "p"},
            {"id": "b", "label": "B", "enabled": True, "username": "b", "password": "p"},
        ],
    )
    service = HttpDownloadService()

    class Client:
        def __init__(self, account_id, quota_remaining):
            self._kikoeru_pikpak_account = service._select_pikpak_account(account_id)
            self.quota_remaining = quota_remaining

        async def get_quota_info(self):
            return {"quota": {"limit": "100", "usage": str(100 - self.quota_remaining), "usage_in_trash": "0"}}

    clients = {"a": Client("a", 40), "b": Client("b", 45)}

    async def fake_client(account_id="", *, account=None):
        return clients[(account.id if account else account_id) or "a"]

    monkeypatch.setattr(service, "_pikpak_client", fake_client)
    monkeypatch.setattr(service, "_close_pikpak_client", lambda _client: asyncio.sleep(0))

    with pytest.raises(HttpDownloadError, match="多账号空间仍不足"):
        await service._copy_pikpak_share_files_multi(
            clients["a"],
            ["huge"],
            [{"id": "huge", "size": 80}],
            share_link="https://mypikpak.com/s/share-id",
        )


@pytest.mark.asyncio
async def test_pikpak_transfer_files_lists_transfer_dir(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def path_to_id(self, path, create=False):
            assert path == "/KikoeruManager"
            return [{"id": "target-folder"}]

        async def file_list(self, size=100, parent_id=None, next_page_token=None):
            assert parent_id == "target-folder"
            return {"files": [{"id": "file-1", "name": "cache.zip", "kind": "drive#file", "size": "12"}]}

    result = await service.pikpak_transfer_files(client=Client())

    assert result["files"][0]["name"] == "cache.zip"
    assert result["files"][0]["size_bytes"] == 12


@pytest.mark.asyncio
async def test_pikpak_transfer_files_lists_parent_id_without_path_lookup(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    class Client:
        async def path_to_id(self, path, create=False):
            raise AssertionError("parent_id 模式不应该重新定位转存目录")

        async def file_list(self, size=100, parent_id=None, next_page_token=None):
            assert parent_id == "folder-child"
            return {"files": [{"id": "file-2", "name": "inner.wav", "kind": "drive#file", "size": "34"}]}

    result = await service.pikpak_transfer_files(client=Client(), parent_id="folder-child")

    assert result["folder_id"] == "folder-child"
    assert result["parent_id"] == "folder-child"
    assert result["files"][0]["name"] == "inner.wav"
    assert result["files"][0]["parent_id"] == "folder-child"


@pytest.mark.asyncio
async def test_delete_pikpak_transfer_items_uses_trash(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, pikpak_enabled=True, pikpak_encoded_token="token")
    service = HttpDownloadService()
    deleted = {}

    class Client:
        async def delete_to_trash(self, ids):
            deleted["ids"] = ids
            return {"ok": True}

        async def get_quota_info(self):
            return {"quota": {"limit": "100", "usage": "50", "usage_in_trash": "10"}}

        async def httpx_client(self):
            return None

    async def fake_client(account_id="", *, account=None):
        client = Client()
        client._kikoeru_pikpak_account = account or service._select_pikpak_account(account_id)
        return client

    async def fake_close(_client):
        return None

    monkeypatch.setattr(service, "_pikpak_client", fake_client)
    monkeypatch.setattr(service, "_close_pikpak_client", fake_close)

    result = await service.delete_pikpak_transfer_items(["file-1"], permanent=False)

    assert deleted["ids"] == ["file-1"]
    assert result["quota"]["remaining_bytes"] == 50
    assert result["account_id"] == "default"


@pytest.mark.asyncio
async def test_clear_pikpak_account_transfer_space_deletes_root_and_trash(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, pikpak_enabled=True, pikpak_encoded_token="token")
    service = HttpDownloadService()
    deleted = []
    list_calls = []

    class Client:
        async def file_list(self, size=100, parent_id=None, next_page_token=None, additional_filters=None):
            list_calls.append((parent_id, additional_filters))
            if parent_id is None:
                return {"files": [{"id": "file-1", "name": "cache.zip", "kind": "drive#file"}]}
            if parent_id == "file-1":
                return {"files": []}
            if parent_id == "*":
                assert additional_filters == {"trashed": {"eq": True}}
                return {"files": [{"id": "trash-1", "name": "old.zip", "kind": "drive#file"}]}
            return {"files": []}

        async def delete_forever(self, ids):
            deleted.append(list(ids))
            return {"ok": True}

        async def get_quota_info(self):
            return {"quota": {"limit": "100", "usage": "0", "usage_in_trash": "0"}}

    async def fake_client(account_id="", *, account=None):
        client = Client()
        client._kikoeru_pikpak_account = account or service._select_pikpak_account(account_id)
        return client

    monkeypatch.setattr(service, "_pikpak_client", fake_client)
    monkeypatch.setattr(service, "_close_pikpak_client", lambda _client: asyncio.sleep(0))

    result = await service.clear_pikpak_account_transfer_space()

    assert deleted == [["file-1"], ["trash-1"]]
    assert (None, {"trashed": {"eq": False}}) in list_calls
    assert ("*", {"trashed": {"eq": True}}) in list_calls
    assert result["deleted_count"] == 2
    assert result["root_deleted_count"] == 1
    assert result["trash_deleted_count"] == 1
    assert result["quota"]["remaining_bytes"] == 100


def test_pikpak_error_explains_quota(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    error = service._pikpak_error(RuntimeError("insufficient storage quota"), "转存分享文件")

    assert "账号空间不足" in str(error)


def test_pikpak_error_hints_country_code_for_captcha_init_params(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    error = service._pikpak_error(
        RuntimeError("meta.username expect 18950976769, but got map[phone_number:+8618950976769 result:accept], please check captcha init params"),
        "登录账号 18950976769",
    )

    text = str(error)
    assert "国家码" in text
    assert "+86" in text


def test_pikpak_status_uses_persisted_cache_by_default(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[{
            "id": "first",
            "label": "一号",
            "username": "first@example.com",
            "password": "pass",
            "transfer_dir": "/KikoeruManager",
        }],
    )
    service = HttpDownloadService()
    monkeypatch.setattr(service, "_pikpak_status_cache_delete_missing", lambda _ids: None)

    def cached_status(account, *, require_fresh=True):
        assert require_fresh is True
        return {
            "success": True,
            "enabled": True,
            "ready": True,
            "account": service._pikpak_account_public(account),
            "account_id": account.id,
            "account_label": account.label,
            "transfer_dir": account.transfer_dir,
            "quota": {"limit_bytes": 100, "usage_bytes": 40, "remaining_bytes": 60},
            "source": "cache",
            "cached": True,
            "cache_updated_at": "2026-01-01T00:00:00",
        }

    async def live_status(*_args, **_kwargs):
        raise AssertionError("默认读取状态不应该重新请求 PikPak")

    monkeypatch.setattr(service, "_pikpak_status_cache_read", cached_status)
    monkeypatch.setattr(service, "_pikpak_account_status", live_status)

    result = asyncio.run(service.pikpak_status())

    assert result["success"] is True
    assert result["cached"] is True
    assert result["accounts"][0]["source"] == "cache"
    assert result["total_remaining_bytes"] == 60


def test_pikpak_status_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[{
            "id": "first",
            "label": "一号",
            "username": "first@example.com",
            "password": "pass",
        }],
    )
    service = HttpDownloadService()
    calls = []
    monkeypatch.setattr(service, "_pikpak_status_cache_delete_missing", lambda _ids: None)
    monkeypatch.setattr(service, "_pikpak_status_cache_read", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("强制刷新不该读缓存")))

    async def live_status(account, *, include_files=False, limit=100):
        calls.append((account.id, include_files, limit))
        return {
            "success": True,
            "enabled": True,
            "ready": True,
            "account": service._pikpak_account_public(account),
            "account_id": account.id,
            "account_label": account.label,
            "transfer_dir": account.transfer_dir,
            "quota": {"limit_bytes": 100, "usage_bytes": 10, "remaining_bytes": 90},
            "source": "live",
            "cached": False,
        }

    monkeypatch.setattr(service, "_pikpak_account_status", live_status)

    result = asyncio.run(service.pikpak_status(force_refresh=True, limit=1))

    assert calls == [("first", False, 1)]
    assert result["cached"] is False
    assert result["accounts"][0]["source"] == "live"


@pytest.mark.asyncio
async def test_pikpak_account_status_falls_back_to_password_when_token_not_found(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, pikpak_enabled=True)
    service = HttpDownloadService()
    account = service._pikpak_account_from_payload({
        "id": "second",
        "label": "二号",
        "username": "second@example.com",
        "password": "pass",
        "encoded_token": "stale-token",
    })
    calls = []

    class Client:
        encoded_token = "stale-token"

        async def user_info(self):
            calls.append("user_info")
            if len(calls) == 1:
                raise RuntimeError("Not Found")
            return {"email": "second@example.com"}

        async def login(self):
            calls.append("login")
            self.encoded_token = "fresh-token"

        async def get_quota_info(self):
            calls.append("quota")
            return {"quota": {"limit": "100", "usage": "25", "usage_in_trash": "0"}}

        async def get_transfer_quota(self):
            return {}

        async def vip_info(self):
            return {}

        class httpx_client:
            @staticmethod
            async def aclose():
                return None

    monkeypatch.setattr(service, "_pikpak_client", lambda *, account=None, account_id="": asyncio.sleep(0, result=Client()))
    monkeypatch.setattr(service, "_save_pikpak_token_callback", lambda *_args, **_kwargs: asyncio.sleep(0))

    result = await service._pikpak_account_status(account)

    assert result["success"] is True
    assert result["quota"]["remaining_bytes"] == 75
    assert calls == ["user_info", "login", "quota"]


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

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        assert headers == {}
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
async def test_resolve_gofile_requires_configured_token(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_guest_token():
        return "guest-token"

    async def fake_fetch_json(url, headers=None, method="GET"):
        assert url == "https://api.gofile.io/contents/content-id"
        assert headers["Authorization"] == "Bearer guest-token"
        return {"status": "ok", "data": {"id": "content-id", "type": "folder", "children": {}}}

    monkeypatch.setattr(service, "_gofile_guest_token", fake_guest_token)
    monkeypatch.setattr(service, "_fetch_json", fake_fetch_json)

    result = await service._collect_gofile_files("https://gofile.io/d/content-id")

    assert result["files"] == []


@pytest.mark.asyncio
async def test_fetch_json_retries_transient_errors(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    calls = 0

    async def fake_sleep(_seconds):
        return None

    async def fake_fetch_json_once(url, headers=None, method="GET"):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("first timeout")
        return {"status": "ok"}

    monkeypatch.setattr("app.core.http_download_service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(service, "_fetch_json_once", fake_fetch_json_once)

    assert await service._fetch_json("https://api.gofile.io/contents/content-id") == {"status": "ok"}
    assert calls == 2


@pytest.mark.asyncio
async def test_gofile_guest_token_caches(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    calls = 0

    async def fake_fetch_json(url, headers=None, method="GET"):
        nonlocal calls
        calls += 1
        assert url == "https://api.gofile.io/accounts"
        assert method == "POST"
        return {"status": "ok", "data": {"token": "guest-token"}}

    monkeypatch.setattr(service, "_fetch_json", fake_fetch_json)

    assert await service._gofile_guest_token() == "guest-token"
    assert await service._gofile_guest_token() == "guest-token"
    assert calls == 1


@pytest.mark.asyncio
async def test_resolve_gofile_folder_files(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path, gofile_token="secret-token")
    service = HttpDownloadService()

    async def fake_fetch_json(url, headers=None, method="GET"):
        assert url == "https://api.gofile.io/contents/content-id"
        assert headers["Authorization"] == "Bearer secret-token"
        assert headers["X-Website-Token"] == service._gofile_website_token("secret-token")
        return {
            "status": "ok",
            "data": {
                "id": "content-id",
                "name": "root",
                "type": "folder",
                "children": {
                    "file-1": {
                        "id": "file-1",
                        "name": "voice.zip",
                        "type": "file",
                        "size": 12,
                        "link": "https://store1.gofile.io/download/direct/voice.zip",
                    }
                },
            },
        }

    monkeypatch.setattr(service, "_fetch_json", fake_fetch_json)

    result = await service._collect_gofile_files("https://gofile.io/d/content-id")

    assert result["files"][0]["filename"] == "voice.zip"
    assert result["files"][0]["source"] == "gofile"
    assert result["files"][0]["aria2_header"] == ["Cookie: accountToken=secret-token"]


@pytest.mark.asyncio
async def test_collect_google_drive_folder_files_from_embedded_folder_view(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    folder_url = "https://drive.google.com/drive/folders/folder-id?usp=sharing"
    file_id = "1A2B3C4D5E6F7G8H9I0J"
    page = f"""<html><body>
      <a class="flip-entry-title" href="https://drive.google.com/file/d/{file_id}/view?usp=drive_web">RJ01581253.zip</a>
    </body></html>"""

    async def fake_fetch_text(url, headers=None):
        assert url == "https://drive.google.com/embeddedfolderview?id=folder-id#list"
        assert headers["User-Agent"]
        return page

    monkeypatch.setattr(service, "_fetch_text", fake_fetch_text)

    result = await service._collect_google_drive_folder_files(folder_url)

    assert result["folder_id"] == "folder-id"
    assert len(result["files"]) == 1
    assert result["files"][0]["source"] == "google_drive"
    assert result["files"][0]["file_id"] == file_id
    assert result["files"][0]["filename"] == "RJ01581253.zip"
    assert result["files"][0]["size_bytes"] == 0
    assert result["files"][0]["url"] == f"https://drive.usercontent.google.com/download?id={file_id}&export=download"


@pytest.mark.asyncio
async def test_collect_google_drive_folder_files_falls_back_to_page_json(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    folder_url = "https://drive.google.com/drive/folders/folder-id?usp=sharing"
    file_id = "1A2B3C4D5E6F7G8H9I0J"
    page = f"""
    <html><script>
    AF_initDataCallback({{key: 'ds:0', data: [[
      ["{file_id}", null, "RJ01581253.zip", "application/zip", 4804731653],
      ["folder-child-id-1234567890", null, "子目录", "application/vnd.google-apps.folder", 0]
    ]] }});
    </script></html>
    """
    fetched = []

    async def fake_fetch_text(url, headers=None):
        fetched.append(url)
        if "embeddedfolderview" in url:
            return "<html><body>empty</body></html>"
        return page

    monkeypatch.setattr(service, "_fetch_text", fake_fetch_text)

    result = await service._collect_google_drive_folder_files(folder_url)

    assert fetched == [
        "https://drive.google.com/embeddedfolderview?id=folder-id#list",
        "https://drive.google.com/drive/folders/folder-id?usp=sharing",
    ]
    assert len(result["files"]) == 1
    assert result["files"][0]["file_id"] == file_id
    assert result["files"][0]["size_bytes"] == 4804731653


@pytest.mark.asyncio
async def test_preview_urls_falls_back_to_google_drive_folder_metadata_when_probe_fails(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://drive.usercontent.google.com/download?id=file-id&export=download"],
            "source_items": [{
                "source": "google_drive",
                "share_url": "https://drive.google.com/drive/folders/folder-id?usp=sharing",
                "url": "https://drive.usercontent.google.com/download?id=file-id&export=download",
                "masked_url": "https://drive.usercontent.google.com/download?query=***",
                "filename": "RJ01581253.zip",
                "size_bytes": 4804731653,
                "file_id": "file-id",
            }],
            "failed_items": [],
            "source_modes": ["google_drive"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        return {"ok": False, "url": raw_url, "reason": "源站返回 HTTP 403"}

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)

    preview = await service.preview_urls(["https://drive.google.com/drive/folders/folder-id?usp=sharing"])

    assert preview["success"] is True
    assert preview["items"][0]["source"] == "google_drive"
    assert preview["items"][0]["filename"] == "RJ01581253.zip"
    assert preview["items"][0]["relative_path"] == "RJ01581253.zip"
    assert preview["items"][0]["file_id"] == "file-id"
    assert "Google Drive" in preview["items"][0]["warning"]


@pytest.mark.asyncio
async def test_preview_urls_keeps_google_drive_folder_filename(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://drive.usercontent.google.com/download?id=file-id&export=download"],
            "source_items": [{
                "source": "google_drive",
                "share_url": "https://drive.google.com/drive/folders/folder-id?usp=sharing",
                "url": "https://drive.usercontent.google.com/download?id=file-id&export=download",
                "masked_url": "https://drive.usercontent.google.com/download?query=***",
                "filename": "RJ01603546.zip",
                "size_bytes": 0,
                "file_id": "file-id",
            }],
            "failed_items": [],
            "source_modes": ["google_drive"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        return {
            "ok": True,
            "url": raw_url,
            "masked_url": service._mask_url(raw_url),
            "host": "drive.usercontent.google.com",
            "source": "google_drive",
            "filename": "download",
            "relative_path": "download",
            "final_path": str(tmp_path / "downloads" / "download"),
            "target_dir": str(tmp_path / "downloads"),
            "size_bytes": 0,
            "resumable": False,
            "warning": "源站返回 HTML 页面，可能不是可直接下载的文件链接。",
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)
    monkeypatch.setattr(
        service,
        "_google_drive_resolve_confirm_url",
        lambda raw_url: asyncio.sleep(
            0,
            result={
                "url": f"{raw_url}&confirm=t&uuid=uuid-token",
                "size_bytes": 1610612736,
                "content_type": "text/html; charset=utf-8",
                "warning": "Google Drive 大文件已自动附加确认下载参数。",
            },
        ),
    )

    preview = await service.preview_urls(["https://drive.google.com/drive/folders/folder-id?usp=sharing"])

    assert preview["items"][0]["filename"] == "RJ01603546.zip"
    assert preview["items"][0]["relative_path"] == "RJ01603546.zip"
    assert preview["items"][0]["size_bytes"] == 1610612736
    assert "confirm=t" in preview["items"][0]["url"]
    assert "确认下载参数" in preview["items"][0]["warning"]


@pytest.mark.asyncio
async def test_preview_urls_uses_source_relative_dir_and_header(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://store1.gofile.io/download/direct/voice.zip"],
            "source_items": [{
                "source": "gofile",
                "url": "https://store1.gofile.io/download/direct/voice.zip",
                "filename": "voice.zip",
                "relative_dir": "folder",
                "size_bytes": 12,
                "headers": {"Cookie": "accountToken=secret-token"},
                "aria2_header": ["Cookie: accountToken=secret-token"],
            }],
            "failed_items": [],
            "source_modes": ["gofile"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        assert headers == {"Cookie": "accountToken=secret-token"}
        return {
            "ok": True,
            "url": raw_url,
            "masked_url": service._mask_url(raw_url),
            "host": "store1.gofile.io",
            "source": "http",
            "filename": "download.bin",
            "relative_path": "download.bin",
            "final_path": str(tmp_path / "downloads" / "download.bin"),
            "target_dir": str(tmp_path / "downloads"),
            "size_bytes": 0,
            "resumable": True,
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)

    preview = await service.preview_urls(["https://gofile.io/d/content-id"], target_subdir="batch")

    assert preview["items"][0]["source"] == "gofile"
    assert preview["items"][0]["relative_path"] == "batch/folder/voice.zip"
    assert preview["items"][0]["aria2_header"] == ["Cookie: accountToken=secret-token"]


@pytest.mark.asyncio
async def test_preview_urls_falls_back_to_gofile_metadata_when_cdn_probe_fails(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://store-na-phx-3.gofile.io/download/web/id/RJ01581253%40SP.zip"],
            "source_items": [{
                "source": "gofile",
                "share_url": "https://gofile.io/d/jrygB9",
                "url": "https://store-na-phx-3.gofile.io/download/web/id/RJ01581253%40SP.zip",
                "masked_url": "https://store-na-phx-3.gofile.io/download/web/id/RJ01581253%40SP.zip",
                "filename": "RJ01581253@SP.zip",
                "relative_dir": "jrygB9",
                "size_bytes": 4804731653,
                "headers": {"Cookie": "accountToken=secret-token"},
                "aria2_header": ["Cookie: accountToken=secret-token"],
            }],
            "failed_items": [],
            "source_modes": ["gofile"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        return {"ok": False, "url": raw_url, "reason": "TimeoutError"}

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)

    preview = await service.preview_urls(["https://gofile.io/d/jrygB9"])

    assert preview["success"] is True
    assert preview["items"][0]["filename"] == "RJ01581253@SP.zip"
    assert preview["items"][0]["relative_path"] == "jrygB9/RJ01581253@SP.zip"
    assert preview["items"][0]["size_bytes"] == 4804731653
    assert "Gofile CDN" in preview["items"][0]["warning"]


@pytest.mark.asyncio
async def test_preview_urls_shows_transferit_as_materialized_item(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": [],
            "source_items": [{
                "source": "transferit",
                "share_url": "https://transfer.it/t/iVqeTDhlyRbA",
                "url": "https://transfer.it/t/iVqeTDhlyRbA",
                "filename": "pack.zip",
                "size_bytes": 12,
                "preview_only": True,
            }],
            "failed_items": [],
            "source_modes": ["transferit"],
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)

    preview = await service.preview_urls(["https://transfer.it/t/iVqeTDhlyRbA"])

    assert preview["needs_materialize"] is True
    assert preview["items"][0]["source"] == "transferit"
    assert "专用下载器" in preview["items"][0]["warning"]


@pytest.mark.asyncio
async def test_collect_transferit_files_retries_busy_response(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    attempts = {"count": 0}

    class FakeTransferit:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def info(self, _url, **_kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("server is busy — try again shortly")
            return [{"name": "pack.zip", "size": 12}]

    async def fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setitem(__import__("sys").modules, "transferit", type("Module", (), {"Transferit": FakeTransferit}))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await service._collect_transferit_files("https://transfer.it/t/iVqeTDhlyRbA")

    assert attempts["count"] == 3
    assert result["files"][0]["filename"] == "pack.zip"


@pytest.mark.asyncio
async def test_collect_transferit_files_falls_back_to_metadata_when_busy(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    attempts = {"count": 0}

    class FakeMetadata:
        def to_json_dict(self):
            return {
                "title": "RJ01580872_v20260413",
                "total_bytes": 623124403,
                "file_count": 1,
                "folder_count": 1,
                "password_protected": False,
                "zip_pending": True,
            }

    class FakeTransferit:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def info(self, _url, **_kwargs):
            attempts["count"] += 1
            raise RuntimeError("server is busy — try again shortly")

        def metadata(self, _url):
            return FakeMetadata()

    async def fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setitem(__import__("sys").modules, "transferit", type("Module", (), {"Transferit": FakeTransferit}))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await service._collect_transferit_files("https://transfer.it/t/iVqeTDhlyRbA")

    assert attempts["count"] == 3
    assert result["files"][0]["filename"] == "RJ01580872_v20260413.zip"
    assert result["files"][0]["size_bytes"] == 623124403
    assert result["files"][0]["metadata_fallback"] is True


@pytest.mark.asyncio
async def test_preview_urls_adds_selection_keys(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    async def fake_resolve_source_urls(urls, materialize=False):
        return {
            "urls": ["https://example.com/a.zip", "https://example.com/b.zip"],
            "source_items": [
                {"source": "http", "url": "https://example.com/a.zip", "masked_url": "https://example.com/a.zip"},
                {"source": "http", "url": "https://example.com/b.zip", "masked_url": "https://example.com/b.zip"},
            ],
            "failed_items": [],
            "source_modes": ["http"],
        }

    async def fake_preview_url(raw_url, target_subdir="", conflict_policy="", headers=None):
        filename = raw_url.rsplit("/", 1)[-1]
        return {
            "ok": True,
            "url": raw_url,
            "masked_url": raw_url,
            "host": "example.com",
            "source": "http",
            "filename": filename,
            "relative_path": filename,
            "final_path": str(tmp_path / filename),
            "target_dir": str(tmp_path),
            "size_bytes": 1,
            "resumable": True,
        }

    monkeypatch.setattr(service, "resolve_source_urls", fake_resolve_source_urls)
    monkeypatch.setattr(service, "preview_url", fake_preview_url)

    preview = await service.preview_urls(["https://example.com/a.zip", "https://example.com/b.zip"])

    assert [item["selection_key"].startswith("http:") for item in preview["items"]] == [True, True]
    assert preview["items"][0]["selection_key"] != preview["items"][1]["selection_key"]


def test_filter_preview_selection_keeps_only_selected_items(tmp_path):
    service = HttpDownloadService()
    preview = {
        "success": True,
        "items": [
            {"ok": True, "source": "http", "masked_url": "https://example.com/a.zip", "filename": "a.zip"},
            {"ok": True, "source": "gofile", "share_url": "https://gofile.io/d/x", "filename": "b.zip"},
            {"ok": False, "source": "http", "masked_url": "https://example.com/bad", "reason": "bad"},
        ],
        "ok_count": 2,
        "failed_count": 1,
    }
    selected_key = service._preview_item_selection_key(preview["items"][1])

    filtered = service.filter_preview_selection(preview, selected_keys=[selected_key])

    assert filtered["ok_count"] == 1
    assert filtered["failed_count"] == 0
    assert filtered["selected_count"] == 1
    assert filtered["items"][0]["filename"] == "b.zip"


def test_preview_item_selection_key_survives_materialized_url_change():
    service = HttpDownloadService()
    preview_item = {
        "ok": True,
        "source": "pikpak",
        "share_url": "https://mypikpak.com/s/share-id",
        "url": "https://mypikpak.com/s/share-id",
        "file_id": "file-1",
        "filename": "voice.zip",
        "relative_path": "folder/voice.zip",
        "size_bytes": 12,
    }
    materialized_item = {
        "ok": True,
        "source": "pikpak",
        "share_url": "https://mypikpak.com/s/share-id",
        "url": "https://cdn.example.com/voice.zip?token=secret",
        "file_id": "file-1",
        "download_file_id": "copied-file-1",
        "filename": "voice.zip",
        "relative_path": "folder/voice.zip",
        "size_bytes": 12,
    }

    assert service._preview_item_selection_key(preview_item) == service._preview_item_selection_key(materialized_item)


def test_preview_item_selection_key_matches_retry_row_without_share_url():
    service = HttpDownloadService()
    failed_row = {
        "source": "pikpak",
        "file_id": "file-004",
        "filename": "RJ01632789.7z.004",
        "relative_path": "RJ01632789.7z.004",
    }
    materialized_item = {
        "ok": True,
        "source": "pikpak",
        "share_url": "https://mypikpak.com/s/share-id",
        "file_id": "file-004",
        "download_file_id": "copy-file-004",
        "filename": "RJ01632789.7z.004",
        "relative_path": "RJ01632789.7z.004",
        "size_bytes": 20,
    }

    assert service._preview_item_selection_key(failed_row) == service._preview_item_selection_key(materialized_item)


def test_preview_item_selection_key_survives_transferit_metadata_fallback():
    service = HttpDownloadService()
    fallback_item = {
        "ok": True,
        "source": "transferit",
        "share_url": "https://transfer.it/t/iVqeTDhlyRbA",
        "share_id": "iVqeTDhlyRbA",
        "filename": "RJ01580872_v20260413.zip",
        "relative_path": "RJ01580872_v20260413.zip",
        "size_bytes": 623124403,
    }
    resolved_item = {
        "ok": True,
        "source": "transferit",
        "share_url": "https://transfer.it/t/iVqeTDhlyRbA",
        "share_id": "iVqeTDhlyRbA",
        "filename": "RJ01580872_20260413182806.zip",
        "relative_path": "RJ01580872_20260413182806.zip",
        "size_bytes": 623124403,
    }

    assert service._preview_item_selection_key(fallback_item) == service._preview_item_selection_key(resolved_item)


def test_retry_selection_items_keep_only_failed_and_incomplete_rows(tmp_path):
    service = HttpDownloadService()
    metadata = {
        "failed_files": [
            {
                "source": "pikpak",
                "name": "RJ01632789.7z.004",
                "relative_path": "RJ01632789.7z.004",
                "file_id": "file-004",
                "status": "failed",
            }
        ],
        "download_files": [
            {
                "source": "pikpak",
                "name": "RJ01632789.7z.001",
                "relative_path": "RJ01632789.7z.001",
                "file_id": "file-001",
                "status": "completed",
                "progress": 100,
                "downloaded": 10,
                "total": 10,
            },
            {
                "source": "pikpak",
                "name": "RJ01632789.7z.004",
                "relative_path": "RJ01632789.7z.004",
                "file_id": "file-004",
                "status": "failed",
                "progress": 73,
                "downloaded": 7,
                "total": 10,
            },
            {
                "source": "pikpak",
                "name": "RJ01632789.7z.010",
                "relative_path": "RJ01632789.7z.010",
                "file_id": "file-010",
                "status": "downloading",
                "progress": 20,
                "downloaded": 2,
                "total": 10,
            },
        ],
    }

    items = service._retry_selection_items_from_task_metadata(metadata)

    assert [item["file_id"] for item in items] == ["file-004", "file-010"]


@pytest.mark.asyncio
async def test_resolve_pikpak_materialize_filters_selected_failed_item(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[{
            "id": "acc-a",
            "label": "A",
            "enabled": True,
            "username": "a",
            "password": "p",
        }],
    )
    service = HttpDownloadService()
    calls = {"copy_ids": [], "download_ids": []}

    class Client:
        pass

    async def fake_collect(_client, raw_url):
        return (
            {"share_id": "share-id", "pass_code_token": ""},
            [
                {"id": "file-001", "name": "RJ01632789.7z.001", "size": 10},
                {"id": "file-004", "name": "RJ01632789.7z.004", "size": 20},
                {"id": "file-010", "name": "RJ01632789.7z.010", "size": 30},
            ],
        )

    async def fake_copy(_client, file_ids, files, **_kwargs):
        calls["copy_ids"].extend(file_ids)
        return (
            {file_id: f"copy-{file_id}" for file_id in file_ids},
            {file_id: service._select_pikpak_account("acc-a") for file_id in file_ids},
        )

    async def fake_download_link(_client, file_id, allow_missing=False):
        calls["download_ids"].append(file_id)
        return {
            "_download_url": f"https://cdn.example.com/{file_id}?token=secret",
            "name": file_id.replace("copy-file-", "RJ01632789.7z."),
            "size": 20,
        }

    monkeypatch.setattr(service, "_pikpak_client", lambda *args, **kwargs: asyncio.sleep(0, result=Client()))
    monkeypatch.setattr(service, "_close_pikpak_client", lambda _client: asyncio.sleep(0))
    monkeypatch.setattr(service, "_collect_pikpak_share_files", fake_collect)
    monkeypatch.setattr(service, "_copy_pikpak_share_files_multi", fake_copy)
    monkeypatch.setattr(service, "_pikpak_download_link", fake_download_link)

    result = await service.resolve_source_urls(
        ["https://mypikpak.com/s/share-id"],
        materialize=True,
        selected_items=[{
            "source": "pikpak",
            "file_id": "file-004",
            "relative_path": "RJ01632789.7z.004",
            "filename": "RJ01632789.7z.004",
        }],
    )

    assert calls["copy_ids"] == ["file-004"]
    assert calls["download_ids"] == ["copy-file-004"]
    assert len(result["source_items"]) == 1
    assert result["source_items"][0]["file_id"] == "file-004"


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


def test_aria2_options_passes_provider_headers(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()

    options = service._aria2_options({"filename": "voice.zip", "aria2_header": ["Cookie: accountToken=secret-token"]}, str(tmp_path))

    assert options["header"] == ["Cookie: accountToken=secret-token"]


@pytest.mark.asyncio
async def test_download_transferit_item_uses_library_download(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    target_dir = tmp_path / "downloads"
    target_dir.mkdir()

    class FakeTransferit:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, link, output_dir):
            assert link == "https://transfer.it/t/iVqeTDhlyRbA"
            Path(output_dir, "pack.zip").write_bytes(b"ok")

    monkeypatch.setitem(__import__("sys").modules, "transferit", type("Module", (), {"Transferit": FakeTransferit}))

    row = await service._download_transferit_item({
        "original_url": "https://transfer.it/t/iVqeTDhlyRbA",
        "filename": "pack.zip",
        "target_dir": str(target_dir),
        "final_path": str(target_dir / "pack.zip"),
        "relative_path": "pack.zip",
        "masked_url": "https://transfer.it/t/iVqeTDhlyRbA",
    })

    assert row["status"] == "completed"
    assert row["size"] == 2


@pytest.mark.asyncio
async def test_download_transferit_item_retries_busy_response(monkeypatch, tmp_path):
    bind_config(monkeypatch, tmp_path)
    service = HttpDownloadService()
    target_dir = tmp_path / "downloads"
    target_dir.mkdir()
    attempts = {"count": 0}

    class FakeTransferit:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, link, output_dir):
            attempts["count"] += 1
            assert link == "https://transfer.it/t/iVqeTDhlyRbA"
            if attempts["count"] < 3:
                raise RuntimeError("server is busy — try again shortly")
            Path(output_dir, "real.zip").write_bytes(b"ok")
            return type("Result", (), {"paths": [str(Path(output_dir, "real.zip"))]})()

    async def fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setitem(__import__("sys").modules, "transferit", type("Module", (), {"Transferit": FakeTransferit}))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    row = await service._download_transferit_item({
        "original_url": "https://transfer.it/t/iVqeTDhlyRbA",
        "filename": "fallback.zip",
        "target_dir": str(target_dir),
        "final_path": str(target_dir / "fallback.zip"),
        "relative_path": "fallback.zip",
        "masked_url": "https://transfer.it/t/iVqeTDhlyRbA",
        "metadata_fallback": True,
    })

    assert attempts["count"] == 3
    assert row["status"] == "completed"
    assert row["name"] == "real.zip"
    assert row["relative_path"] == "real.zip"


@pytest.mark.asyncio
async def test_cleanup_completed_pikpak_transfer_items_only_deletes_success_rows(monkeypatch, tmp_path):
    bind_config(
        monkeypatch,
        tmp_path,
        pikpak_enabled=True,
        pikpak_accounts=[
            {"id": "acc-a", "label": "A", "enabled": True, "username": "a", "password": "p"},
            {"id": "acc-b", "label": "B", "enabled": True, "username": "b", "password": "p"},
        ],
    )
    service = HttpDownloadService()
    calls = []

    async def fake_delete(ids, *, permanent=False, account_id=""):
        calls.append((account_id, list(ids), permanent))
        return {
            "success": True,
            "deleted_count": len(ids),
            "requested_count": len(ids),
            "permanent": permanent,
            "account_id": account_id,
        }

    monkeypatch.setattr(service, "delete_pikpak_transfer_items", fake_delete)

    result = await service.cleanup_completed_pikpak_transfer_items([
        {
            "source": "pikpak",
            "status": "completed",
            "download_file_id": "copied-a",
            "pikpak_materialized": True,
            "pikpak_account_id": "acc-a",
        },
        {
            "source": "pikpak",
            "status": "failed",
            "pikpak_cleanup_file_id": "failed-copy",
            "pikpak_account_id": "acc-a",
        },
        {
            "source": "pikpak",
            "status": "completed",
            "pikpak_cleanup_file_id": "copied-b",
            "pikpak_account_id": "acc-b",
        },
        {
            "source": "http",
            "status": "completed",
            "pikpak_cleanup_file_id": "not-pikpak",
            "pikpak_account_id": "acc-a",
        },
    ])

    assert result["success"] is True
    assert result["requested_count"] == 2
    assert result["deleted_count"] == 2
    assert calls == [
        ("acc-a", ["copied-a"], True),
        ("acc-b", ["copied-b"], True),
    ]
