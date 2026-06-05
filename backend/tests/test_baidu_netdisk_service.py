import pytest

from app.api import routes
from app.core.baidu_netdisk_service import BaiduNetdiskService
from app.core.task_engine import Task, TaskStatus, TaskType


class DummyBaiduConfig:
    enabled = True
    cookie = "BDUSS=test; STOKEN=test"
    account_uk = "account-uk"
    download_root = ""
    baidupcs_go_path = "tools/baidupcs-go/BaiduPCS-Go.exe"
    config_dir = ""
    max_parallel = 200
    max_download_load = "0"
    conflict_policy = "resume"
    svip_speed_enabled = True
    vip_type = 0
    vip_label = ""


class DummyHttpDownloader:
    download_root = ""
    proxy_url = ""
    retry_count = 1
    retry_wait_seconds = 0
    connect_timeout_seconds = 15
    timeout_seconds = 60


class DummyStorage:
    input_path = ""
    temp_path = "/tmp"


class DummyConfig:
    baidu_netdisk = DummyBaiduConfig()
    http_downloader = DummyHttpDownloader()
    storage = DummyStorage()


@pytest.mark.asyncio
async def test_baidu_preview_reads_share_file_detail(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())

    async def fake_tokens(feature, cookie, *, referer=""):
        assert feature == "13EU1GlLvUULM43mkqhoZxA"
        return {"bdstoken": "token", "shareid": "share-id", "share_uk": "uk"}

    async def fake_verify(url, cookie, *, data=None, referer="", timeout=20):
        assert url.startswith("http://pan.baidu.com/share/verify?")
        assert "shareid=share-id" in url
        assert "uk=uk" in url
        assert "surl=" not in url
        assert "channel=" not in url
        assert "bdstoken=" not in url
        assert data["pwd"] == "38a2"
        assert "bdstoken" not in data
        assert referer == "https://pan.baidu.com/share/init?surl=3EU1GlLvUULM43mkqhoZxA"
        return {"errno": 0, "randsk": "randsk"}

    async def fake_json(url, cookie, timeout=20, referer=""):
        assert "share/list" in url
        assert "uk=uk" in url
        assert "shareid=share-id" in url
        assert "sekey=randsk" in url
        assert "BDCLND=randsk" in cookie
        if "root=0" in url:
            return {
                "errno": 0,
                "list": [
                    {"server_filename": "track01.wav", "path": "/RJ123456 作品本体/track01.wav", "isdir": 0, "size": 1048576, "fs_id": 1002},
                    {"server_filename": "subtitles", "path": "/RJ123456 作品本体/subtitles", "isdir": 1, "size": 0, "fs_id": 1003},
                ],
            }
        return {
            "errno": 0,
            "list": [
                {"server_filename": "RJ123456 作品本体", "path": "/RJ123456 作品本体", "isdir": 1, "size": 0, "fs_id": 1001},
            ],
        }

    monkeypatch.setattr(service, "_fetch_share_page_tokens", fake_tokens)
    monkeypatch.setattr(service, "_fetch_form_json", fake_verify)
    monkeypatch.setattr(service, "_fetch_json", fake_json)

    preview = await service.preview_urls(["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"])
    item = preview["items"][0]

    assert item["ok"] is True
    assert item["filename"] == "RJ123456 作品本体"
    assert item["preview_file_count"] == 2
    assert item["preview_folder_count"] == 1
    assert item["preview_files"][0]["name"] == "track01.wav"
    assert item["preview_files"][0]["relative_path"] == "RJ123456 作品本体/track01.wav"
    assert item["preview_summary"].startswith("包含 2 项")
    assert item["size_bytes"] == 1048576


def test_baidu_separator_rule_keeps_existing_pass_code_rules(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_config", lambda: DummyConfig())

    separated = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA----38a2",
    ])
    legacy = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        "提取码 38a2",
    ])

    assert separated == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]
    assert legacy == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA", "提取码 38a2"]


@pytest.mark.asyncio
async def test_baidu_start_download_uses_official_sharedownload_direct_stream(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.download_root = str(tmp_path / "downloads")
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    captured = {"sharedownload": None, "stream_headers": None}

    async def fake_preview_urls(*_args, **_kwargs):
        return {
            "items": [{
                "ok": True,
                "selection_key": "baidu:item",
                "filename": "RJ01534331",
                "share_url": "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
                "share_id": "13EU1GlLvUULM43mkqhoZxA",
                "share_numeric_id": "98765",
                "share_uk": "share-uk",
                "bdstoken": "bd-token",
                "randsk": "rand-sk",
                "shorturl": "13EU1GlLvUULM43mkqhoZxA",
                "share_sign": "share-sign",
                "share_timestamp": "1717420000",
                "share_files": [{
                    "name": "RJ01534331.rar",
                    "relative_path": "RJ01534331.rar",
                    "path": "/RJ01534331.rar",
                    "is_dir": False,
                    "size_bytes": 6,
                    "fs_id": "4436827288",
                }],
            }],
            "selected_keys": ["baidu:item"],
            "ok_count": 1,
            "success": True,
        }

    async def fake_fetch_form_json(url, cookie, *, data=None, referer="", timeout=20):
        captured["sharedownload"] = {
            "url": url,
            "cookie": cookie,
            "data": dict(data or {}),
            "referer": referer,
        }
        return {"errno": 0, "list": [{"dlink": "https://d.pcs.baidu.com/file/rj.rar"}]}

    class FakeContent:
        async def iter_chunked(self, _size):
            yield b"abc"
            yield b"def"

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/octet-stream", "content-length": "6"}
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def get(self, url, *, headers=None, allow_redirects=True, proxy=None):
            captured["stream_headers"] = {
                "url": url,
                "headers": dict(headers or {}),
                "allow_redirects": allow_redirects,
                "proxy": proxy,
            }
            return FakeResponse()

    monkeypatch.setattr(service, "preview_urls", fake_preview_urls)
    monkeypatch.setattr(service, "_fetch_form_json", fake_fetch_form_json)
    monkeypatch.setattr("app.core.baidu_netdisk_service.aiohttp.ClientSession", FakeSession)

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"],
            "batch_name": "百度直下测试",
            "conflict_policy": "resume",
        },
        status=TaskStatus.PROCESSING,
        task_id="baidu-test-task",
    )

    result = await service.start_download_task(task)

    assert result["success"] is True
    assert (tmp_path / "downloads" / "百度直下测试" / "RJ01534331.rar").read_bytes() == b"abcdef"
    assert "api/sharedownload" in captured["sharedownload"]["url"]
    assert "transfer" not in captured["sharedownload"]["url"]
    assert captured["sharedownload"]["data"]["fid_list"] == "[4436827288]"
    assert captured["sharedownload"]["data"]["primaryid"] == "98765"
    assert captured["sharedownload"]["data"]["uk"] == "share-uk"
    assert "BDCLND=rand-sk" in captured["sharedownload"]["cookie"]
    assert captured["stream_headers"]["url"] == "https://d.pcs.baidu.com/file/rj.rar"
    assert captured["stream_headers"]["headers"]["Cookie"].startswith("BDUSS=test")
    assert captured["stream_headers"]["headers"]["User-Agent"].startswith("netdisk;")
    assert task.task_metadata["download_files"][0]["status"] == "completed"
    assert task.task_metadata["download_files"][0]["downloaded"] == 6
    assert task.task_metadata["download_runtime"]["completed_files"] == 1
