from pathlib import Path
import time

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


@pytest.mark.asyncio
async def test_baidu_share_page_tokens_prefer_locals_mset_without_tplconfig(monkeypatch):
    service = BaiduNetdiskService()
    responses = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body.encode("utf-8")

    def fake_urlopen(request, timeout=20):
        url = request.full_url
        responses.append(url)
        return FakeResponse(
            """
            <script>new BadJs({rules:{path: /(\\/s\\/\\w|.*)/}, loginstate: false});</script>
            <script>window.yunData={bdstoken:'', uk:'0', loginstate:'0', share_uk:"bad", shareid:"bad"};</script>
            <script>locals.mset({"page":{"nested":{"ok":true}},"uk":"1799206866","loginstate":1,"bdstoken":"bd-token","share_uk":"1635081079","shareid":60130084160});</script>
            """
        )

    monkeypatch.setattr("app.core.baidu_netdisk_service.urlopen", fake_urlopen)

    tokens = await service._fetch_share_page_tokens("179-Q_PpccuyitQ2b_boyDw", "BDUSS=test")

    assert responses[0] == "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw"
    assert tokens == {
        "bdstoken": "bd-token",
        "uk": "1799206866",
        "share_uk": "1635081079",
        "shareid": "60130084160",
        "sign": "",
        "timestamp": "",
    }


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


def test_baidu_pcsgo_output_updates_download_runtime(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-progress-test-task",
    )
    row = {
        "name": "狩龙人拉格纳121.mp4",
        "relative_path": "狩龙人拉格纳121.mp4",
        "status": "downloading",
        "progress": 0,
        "downloaded": 0,
        "total": 0,
        "size": 0,
        "speed_bytes_per_sec": 0,
    }
    download_files = [row]

    service._update_pcsgo_transfer_progress(
        task,
        row,
        download_files,
        time.monotonic() - 5,
        "下载中 12.5MiB/100MiB 12.5% 3.5MiB/s",
        {"last_emit_at": 0.0, "last_log_at": 0.0},
    )

    assert row["progress"] == 12
    assert row["downloaded"] == int(12.5 * 1024 * 1024)
    assert row["total"] == 100 * 1024 * 1024
    assert row["speed_bytes_per_sec"] == int(3.5 * 1024 * 1024)
    assert task.task_metadata["download_runtime"]["transferred_bytes"] == row["downloaded"]
    assert task.task_metadata["download_runtime"]["speed_bytes_per_sec"] == row["speed_bytes_per_sec"]
    assert any("BaiduPCS-Go" in item["message"] for item in task.task_metadata["progress_log"])


@pytest.mark.asyncio
async def test_baidu_start_route_reuses_cached_preview_and_keeps_raw_selected_items(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    raw_preview = {
        "success": True,
        "source": "baidu_netdisk",
        "source_label": "百度网盘",
        "download_mode": "baidu_netdisk",
        "items": [{
            "ok": True,
            "selection_key": "baidu:item",
            "filename": "百度大文件",
            "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
            "share_id": "179-Q_PpccuyitQ2b_boyDw",
            "share_numeric_id": "60130084160",
            "share_uk": "1635081079",
            "bdstoken": "bd-token",
            "randsk": "rand-sk",
            "shorturl": "179-Q_PpccuyitQ2b_boyDw",
            "share_sign": "share-sign",
            "share_timestamp": "1780634067",
            "share_files": [{
                "name": "狩龙人拉格纳121.mp4",
                "relative_path": "狩龙人拉格纳121.mp4",
                "path": "/狩龙人拉格纳121.mp4",
                "is_dir": False,
                "size_bytes": 6,
                "fs_id": "732325025154301",
            }],
        }],
        "source_items": [],
        "selected_keys": ["baidu:item"],
        "ok_count": 1,
        "failed_count": 0,
        "selected_count": 1,
    }
    cache_key = service.raw_preview_cache_key(
        ["https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402"],
        target_subdir="",
        conflict_policy="resume",
        output_folder_name="百度大文件测试",
    )
    service._raw_preview_cache[cache_key] = {"cached_at": __import__("time").monotonic(), "preview": raw_preview}
    monkeypatch.setattr(service, "preview_urls", lambda *_args, **_kwargs: pytest.fail("缓存命中后不应重新预览"))
    monkeypatch.setattr(service, "account_status", lambda: {"is_svip": False})

    submitted = {}

    class FakeEngine:
        async def submit(self, task):
            submitted["task"] = task
            return task.id

    monkeypatch.setattr("app.core.baidu_netdisk_service.get_baidu_netdisk_service", lambda: service)
    monkeypatch.setattr("app.core.task_engine.get_task_engine", lambda: FakeEngine())

    request = routes.BaiduNetdiskStartRequest(
        urls=["https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402"],
        output_folder_name="百度大文件测试",
        conflict_policy="resume",
        selected_keys=["baidu:item"],
        selected_items=[{"selection_key": "baidu:item"}],
    )

    result = await routes.baidu_netdisk_start(request)

    assert result["success"] is True
    assert submitted["task"].task_metadata["raw_preview_cache_key"] == cache_key
    assert submitted["task"].task_metadata["raw_selected_items"][0]["share_files"][0]["name"] == "狩龙人拉格纳121.mp4"


@pytest.mark.asyncio
async def test_baidu_start_download_uses_pcsgo_temporary_transfer_and_cleans_remote_dir(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.download_root = str(tmp_path / "downloads")
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    command_log = []
    state = {}
    remote_tmp_dir = "/km_20260605_153012_a1b2c3"

    async def fake_preview_urls(*_args, **_kwargs):
        return {
            "items": [{
                "ok": True,
                "selection_key": "baidu:item",
                "filename": "百度大文件",
                "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
                "share_id": "179-Q_PpccuyitQ2b_boyDw",
                "share_numeric_id": "60130084160",
                "share_uk": "1635081079",
                "bdstoken": "bd-token",
                "randsk": "rand-sk",
                "shorturl": "179-Q_PpccuyitQ2b_boyDw",
                "share_sign": "share-sign",
                "share_timestamp": "1780634067",
                "share_files": [{
                    "name": "狩龙人拉格纳121.mp4",
                    "relative_path": "狩龙人拉格纳121.mp4",
                    "path": "/狩龙人拉格纳121.mp4",
                    "is_dir": False,
                    "size_bytes": 6,
                    "fs_id": "732325025154301",
                }],
            }],
            "selected_keys": ["baidu:item"],
            "ok_count": 1,
            "success": True,
        }

    async def fake_run_baidu_pcs_go_command(
        args,
        *,
        env,
        log_path,
        task,
        cancel_event,
        ignore_task_cancel=False,
        on_output=None,
        heartbeat_message="",
    ):
        command_log.append({
            "args": tuple(args[1:]),
            "ignore_task_cancel": ignore_task_cancel,
        })
        command = args[1]
        if command == "config":
            if args[3] == "-savedir":
                state["savedir"] = args[-1]
            return
        if command == "download":
            savedir = args[args.index("--saveto") + 1]
            downloaded = Path(savedir) / "狩龙人拉格纳121.mp4"
            downloaded.parent.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"abcdef")
            return
        if command in {"login", "cd", "mkdir", "rm", "transfer"}:
            return
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(service, "preview_urls", fake_preview_urls)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: remote_tmp_dir)
    monkeypatch.setattr(service, "_fetch_form_json", lambda *_args, **_kwargs: pytest.fail("不应该再请求官方 sharedownload"))

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": ["https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402"],
            "batch_name": "百度大文件测试",
            "conflict_policy": "resume",
        },
        status=TaskStatus.PROCESSING,
        task_id="baidu-large-test-task",
    )

    result = await service.start_download_task(task)

    assert result["success"] is True
    assert (tmp_path / "downloads" / "百度大文件测试" / "狩龙人拉格纳121.mp4").read_bytes() == b"abcdef"
    savedir = state["savedir"]
    assert [item["args"] for item in command_log] == [
        ("login", "-cookies=BDUSS=test; STOKEN=test; BDCLND=rand-sk"),
        ("config", "set", "-savedir", savedir),
        ("config", "set", "-max_parallel", "20"),
        ("config", "set", "-max_download_load", "5"),
        ("config", "set", "-max_download_rate", "0"),
        ("config", "set", "-cache_size", "256KB"),
        ("cd", "/"),
        ("mkdir", remote_tmp_dir),
        ("cd", remote_tmp_dir),
        ("transfer", "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402", "--collect"),
        ("download", remote_tmp_dir, "--saveto", savedir, "--mode", "locate", "-p", "20", "-l", "5", "--retry", "5"),
        ("cd", "/"),
        ("rm", remote_tmp_dir),
    ]
    assert all(not item["ignore_task_cancel"] for item in command_log[:-2])
    assert all(item["ignore_task_cancel"] for item in command_log[-2:])
    assert Path(savedir).name == "download"
    assert remote_tmp_dir.startswith("/km_")
    assert len(remote_tmp_dir) <= 32
    assert any("临时转存" in item["message"] for item in task.task_metadata["progress_log"])
    assert any("已删除百度网盘临时转存目录" in item["message"] for item in task.task_metadata["progress_log"])
    assert task.task_metadata["download_files"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_baidu_start_download_prefers_raw_selected_items_without_preview(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.download_root = str(tmp_path / "downloads")
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    command_log = []
    state = {}
    raw_item = {
        "ok": True,
        "selection_key": "baidu:item",
        "filename": "百度大文件",
        "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
        "share_id": "179-Q_PpccuyitQ2b_boyDw",
        "share_numeric_id": "60130084160",
        "share_uk": "1635081079",
        "bdstoken": "bd-token",
        "randsk": "rand-sk",
        "shorturl": "179-Q_PpccuyitQ2b_boyDw",
        "share_sign": "share-sign",
        "share_timestamp": "1780634067",
        "share_files": [{
            "name": "狩龙人拉格纳121.mp4",
            "relative_path": "狩龙人拉格纳121.mp4",
            "path": "/狩龙人拉格纳121.mp4",
            "is_dir": False,
            "size_bytes": 6,
            "fs_id": "732325025154301",
        }],
    }

    async def fake_run_baidu_pcs_go_command(
        args,
        *,
        env,
        log_path,
        task,
        cancel_event,
        ignore_task_cancel=False,
        on_output=None,
        heartbeat_message="",
    ):
        command_log.append({
            "args": tuple(args[1:]),
            "ignore_task_cancel": ignore_task_cancel,
        })
        command = args[1]
        if command == "config":
            if args[3] == "-savedir":
                state["savedir"] = args[-1]
            return
        if command == "download":
            savedir = args[args.index("--saveto") + 1]
            downloaded = Path(savedir) / "狩龙人拉格纳121.mp4"
            downloaded.parent.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"abcdef")
            return
        if command in {"login", "cd", "mkdir", "rm", "transfer"}:
            return
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(service, "preview_urls", lambda *_args, **_kwargs: pytest.fail("raw_selected_items 已提供，不应重新预览"))
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_20260605_153012_a1b2c3")
    monkeypatch.setattr(service, "_fetch_form_json", lambda *_args, **_kwargs: pytest.fail("不应该再请求官方 sharedownload"))

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": ["https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402"],
            "raw_selected_items": [raw_item],
            "batch_name": "百度大文件测试",
            "conflict_policy": "resume",
        },
        status=TaskStatus.PROCESSING,
        task_id="baidu-large-raw-selected-test-task",
    )

    result = await service.start_download_task(task)

    assert result["success"] is True
    assert (tmp_path / "downloads" / "百度大文件测试" / "狩龙人拉格纳121.mp4").read_bytes() == b"abcdef"
    assert [item["args"] for item in command_log][0] == ("login", "-cookies=BDUSS=test; STOKEN=test; BDCLND=rand-sk")
    assert any(
        item["args"] == ("download", "/km_20260605_153012_a1b2c3", "--saveto", state["savedir"], "--mode", "locate", "-p", "20", "-l", "5", "--retry", "5")
        for item in command_log
    )
    assert task.task_metadata["download_files"][0]["status"] == "completed"
