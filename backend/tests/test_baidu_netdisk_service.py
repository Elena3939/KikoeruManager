import asyncio
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app.api import routes
from app.core.baidu_netdisk_service import BaiduNetdiskError, BaiduNetdiskLowSpeedError, BaiduNetdiskService
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
    def __init__(self):
        self.baidu_netdisk = DummyBaiduConfig()
        self.http_downloader = DummyHttpDownloader()
        self.storage = DummyStorage()


@pytest.mark.asyncio
async def test_baidu_preview_reads_share_file_detail(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())
    monkeypatch.setattr(service, "_make_web_logid", lambda _cookie: "log-id")

    async def fake_tokens(feature, cookie, *, referer=""):
        assert feature == "13EU1GlLvUULM43mkqhoZxA"
        return {"bdstoken": "token", "shareid": "share-id", "share_uk": "uk"}

    async def fake_verify(url, cookie, *, data=None, referer="", timeout=20, use_requests=False):
        assert url.startswith("https://pan.baidu.com/share/verify?")
        assert "surl=3EU1GlLvUULM43mkqhoZxA" in url
        assert "channel=chunlei" in url
        assert "web=1" in url
        assert "app_id=250528" in url
        assert "bdstoken=token" in url
        assert "clienttype=0" in url
        assert "logid=" in url
        assert "dp-logid=" in url
        assert "shareid=share-id" not in url
        assert data["pwd"] == "38a2"
        assert data["vcode"] == ""
        assert data["vcode_str"] == ""
        assert referer == "https://pan.baidu.com/share/init?surl=3EU1GlLvUULM43mkqhoZxA"
        assert use_requests is True
        return {"errno": 0, "randsk": "randsk"}

    async def fake_json(url, cookie, timeout=20, referer="", use_requests=False):
        assert "share/list" in url
        assert "BDCLND=randsk" in cookie
        assert use_requests is True
        if "root=0" in url:
            assert "uk=uk" in url
            assert "shareid=share-id" in url
            assert "sekey=randsk" in url
            return {
                "errno": 0,
                "list": [
                    {"server_filename": "track01.wav", "path": "/RJ123456 作品本体/track01.wav", "isdir": 0, "size": 1048576, "fs_id": 1002},
                    {"server_filename": "subtitles", "path": "/RJ123456 作品本体/subtitles", "isdir": 1, "size": 0, "fs_id": 1003},
                ],
            }
        assert "web=5" in url
        assert "shorturl=3EU1GlLvUULM43mkqhoZxA" in url
        assert "root=1" in url
        assert "view_mode=1" in url
        assert "uk=uk" not in url
        assert "shareid=share-id" not in url
        assert "sekey=randsk" not in url
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
async def test_baidu_preview_marks_wrong_pass_code_as_retryable(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())
    monkeypatch.setattr(service, "_make_web_logid", lambda _cookie: "log-id")
    monkeypatch.setattr(service, "_make_dp_logid", lambda: "dp-log-id")

    async def fake_tokens(feature, cookie, *, referer=""):
        assert feature == "13EU1GlLvUULM43mkqhoZxA"
        return {"bdstoken": "token", "shareid": "share-id", "share_uk": "uk"}

    async def fake_verify(url, cookie, *, data=None, referer="", timeout=20, use_requests=False):
        assert url.startswith("https://pan.baidu.com/share/verify?")
        assert data["pwd"] == "38a21"
        assert use_requests is True
        return {"errno": -12, "errmsg": "提取码错误"}

    monkeypatch.setattr(service, "_fetch_share_page_tokens", fake_tokens)
    monkeypatch.setattr(service, "_fetch_form_json", fake_verify)
    monkeypatch.setattr(service, "_fetch_json", lambda *_args, **_kwargs: pytest.fail("错误提取码不应继续读取分享列表"))

    preview = await service.preview_urls(["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a21"])
    item = preview["items"][0]

    assert preview["success"] is False
    assert preview["needs_pass_code_count"] == 1
    assert item["ok"] is False
    assert item["requires_pass_code"] is True
    assert item["pass_code_invalid"] is True
    assert item["reason"] == "提取码错误"
    assert item["warning"] == "提取码错误，请重新输入"


@pytest.mark.asyncio
async def test_baidu_share_list_retries_with_init_referer_after_redirect_loop(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())
    referers = []

    async def fake_json(url, cookie, timeout=20, referer="", use_requests=False):
        assert "share/list" in url
        assert "web=5" in url
        assert "shorturl=3EU1GlLvUULM43mkqhoZxA" in url
        assert "view_mode=1" in url
        assert use_requests is True
        referers.append(referer)
        if referer.endswith("/s/13EU1GlLvUULM43mkqhoZxA"):
            raise RuntimeError("HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop")
        return {
            "errno": 0,
            "list": [
                {"server_filename": "track01.wav", "path": "/track01.wav", "isdir": 0, "size": 1048576, "fs_id": 1002},
            ],
        }

    monkeypatch.setattr(service, "_fetch_json", fake_json)

    result = await service._fetch_share_list_payload(
        {"bdstoken": "token", "shareid": "share-id", "share_uk": "uk"},
        "BDUSS=test",
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        "13EU1GlLvUULM43mkqhoZxA",
    )

    assert result["errno"] == 0
    assert referers[:2] == [
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        "https://pan.baidu.com/share/init?surl=3EU1GlLvUULM43mkqhoZxA",
    ]


@pytest.mark.asyncio
async def test_baidu_share_page_tokens_prefer_locals_mset_without_tplconfig(monkeypatch):
    service = BaiduNetdiskService()
    responses = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        text = property(lambda self: self.body)

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, url, headers=None, timeout=20, allow_redirects=True):
            responses.append(url)
            return FakeResponse(
                """
                <script>new BadJs({rules:{path: /(\\/s\\/\\w|.*)/}, loginstate: false});</script>
                <script>window.yunData={bdstoken:'', uk:'0', loginstate:'0', share_uk:"bad", shareid:"bad"};</script>
                <script>locals.mset({"page":{"nested":{"ok":true}},"uk":"1799206866","loginstate":1,"bdstoken":"bd-token","share_uk":"1635081079","shareid":60130084160});</script>
                """
            )

    monkeypatch.setattr("app.core.baidu_netdisk_service.requests.Session", lambda: FakeSession())

    tokens = await service._fetch_share_page_tokens("179-Q_PpccuyitQ2b_boyDw", "BDUSS=test")

    assert responses[0] == "https://pan.baidu.com/share/init?surl=79-Q_PpccuyitQ2b_boyDw"
    assert {
        key: tokens[key]
        for key in ("bdstoken", "uk", "share_uk", "shareid", "sign", "timestamp")
    } == {
        "bdstoken": "bd-token",
        "uk": "1799206866",
        "share_uk": "1635081079",
        "shareid": "60130084160",
        "sign": "",
        "timestamp": "",
    }
    assert tokens["_page_payload"]["page"]["nested"]["ok"] is True


@pytest.mark.asyncio
async def test_baidu_share_page_tokens_retry_init_after_redirect_loop(monkeypatch):
    service = BaiduNetdiskService()
    responses = []

    class FakeResponse:
        text = """
            <script>locals.mset({"uk":"1799206866","bdstoken":"bd-token","share_uk":"1635081079","shareid":60130084160});</script>
            """

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, url, headers=None, timeout=20, allow_redirects=True):
            responses.append(url)
            if url.endswith("share/init?surl=79-Q_PpccuyitQ2b_boyDw"):
                raise RuntimeError("HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop")
            return FakeResponse()

    monkeypatch.setattr("app.core.baidu_netdisk_service.requests.Session", lambda: FakeSession())

    tokens = await service._fetch_share_page_tokens("179-Q_PpccuyitQ2b_boyDw", "BDUSS=test")

    assert responses == [
        "https://pan.baidu.com/share/init?surl=79-Q_PpccuyitQ2b_boyDw",
        "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw",
    ]
    assert tokens["shareid"] == "60130084160"
    assert tokens["share_uk"] == "1635081079"


@pytest.mark.asyncio
async def test_baidu_share_list_uses_page_payload_when_all_referers_fail(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())

    async def fake_json(_url, _cookie, timeout=20, referer=""):
        raise RuntimeError("HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop")

    monkeypatch.setattr(service, "_fetch_json", fake_json)

    result = await service._fetch_share_list_payload(
        {
            "bdstoken": "bd-token",
            "shareid": "60130084160",
            "share_uk": "1635081079",
            "_page_payload": {
                "page": {
                    "file_list": [
                        {"server_filename": "voice01.wav", "path": "/voice01.wav", "isdir": 0, "size": 2048, "fs_id": 1001},
                        {"title": "not-file-row"},
                    ],
                },
            },
        },
        "BDUSS=test",
        "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw",
        "179-Q_PpccuyitQ2b_boyDw",
    )

    assert result["errno"] == 0
    assert result["_source"] == "share_page_payload"
    assert result["list"] == [
        {"server_filename": "voice01.wav", "path": "/voice01.wav", "isdir": 0, "size": 2048, "fs_id": 1001},
    ]


def test_baidu_separator_rule_keeps_existing_pass_code_rules(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_config", lambda: DummyConfig())

    separated = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA----38a2",
    ])
    inline = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA  38a2",
    ])
    inline_label = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA 提取码：38a2",
    ])
    legacy = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        "提取码 38a2",
    ])
    combined = routes._baidu_netdisk_urls_from_payload([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA----38a2",
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
        "38a2",
    ])

    assert separated == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]
    assert inline == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]
    assert inline_label == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]
    assert legacy == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]
    assert combined == ["https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"]


def test_baidu_parse_share_url_reads_inline_pass_code():
    service = BaiduNetdiskService()

    share = service._parse_share_url("https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA  38a2")

    assert share["share_url"] == "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"
    assert share["pass_code"] == "38a2"


def test_baidu_parse_share_inputs_merges_duplicate_share_and_pass_code():
    service = BaiduNetdiskService()

    shares = service.parse_share_inputs([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA----38a2",
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
        "38a2",
    ])

    assert len(shares) == 1
    assert shares[0]["share_url"] == "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"
    assert shares[0]["pass_code"] == "38a2"


def test_baidu_parse_share_inputs_appends_following_pass_code_to_share_url():
    service = BaiduNetdiskService()

    shares = service.parse_share_inputs([
        "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        "38a2",
    ])

    assert len(shares) == 1
    assert shares[0]["share_url"] == "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2"
    assert shares[0]["pass_code"] == "38a2"


def test_baidu_pcsgo_zero_exit_failure_output_is_error():
    service = BaiduNetdiskService()

    assert service._pcsgo_command_failure_message("分享链接转存到网盘失败: 获取分享项元数据错误") == "分享链接转存到网盘失败: 获取分享项元数据错误"
    assert service._pcsgo_command_failure_message("WARNING: config init error: ignored\n百度帐号登录成功: tester") == ""


def test_baidu_share_sekey_decodes_encoded_randsk_once():
    service = BaiduNetdiskService()

    assert service._baidu_share_sekey("uzjNNR%2BOtCzO%2B7jt7ksocH7T8vkGYZqURizMmjySHhE%3D") == "uzjNNR+OtCzO+7jt7ksocH7T8vkGYZqURizMmjySHhE="
    assert service._baidu_share_sekey("plain+value=") == "plain+value="


def test_baidu_custom_name_uses_filename_password_template(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_name": "RJ01534331",
            "custom_extract_password": "SOUTH+",
        },
        [{
            "name": "RJ01534331.rar",
            "relative_path": "RJ01534331.rar",
            "original_name": "RJ01534331.rar",
            "original_relative_path": "RJ01534331.rar",
        }],
    )

    assert rows[0]["name"] == "RJ01534331（SOUTH+）.rar"
    assert rows[0]["relative_path"] == "RJ01534331（SOUTH+）.rar"
    assert rows[0]["custom_rename_applied"] is True


def test_baidu_custom_name_skips_multi_file_share():
    service = BaiduNetdiskService()

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_name": "RJ01534331",
            "custom_extract_password": "SOUTH+",
        },
        [
            {"name": "track01.wav", "relative_path": "track01.wav"},
            {"name": "track02.wav", "relative_path": "track02.wav"},
        ],
    )

    assert [row["relative_path"] for row in rows] == ["track01.wav", "track02.wav"]
    assert all(row["custom_rename_skipped"] is True for row in rows)


def test_baidu_preview_strips_virtual_common_parent_without_real_dir():
    service = BaiduNetdiskService()

    rows = service._strip_virtual_common_parent_from_preview_files([
        {
            "name": "RJ01635228.7z.001kk",
            "relative_path": "RJ01635228.7z/RJ01635228.7z.001kk",
            "is_dir": False,
        },
        {
            "name": "RJ01635228.7z.002kk",
            "relative_path": "RJ01635228.7z/RJ01635228.7z.002kk",
            "is_dir": False,
        },
    ])

    assert [row["relative_path"] for row in rows] == [
        "RJ01635228.7z.001kk",
        "RJ01635228.7z.002kk",
    ]


def test_baidu_preview_keeps_real_root_dir():
    service = BaiduNetdiskService()

    rows = service._strip_virtual_common_parent_from_preview_files([
        {"name": "RJ123456", "relative_path": "RJ123456", "is_dir": True},
        {"name": "track01.wav", "relative_path": "RJ123456/track01.wav", "is_dir": False},
        {"name": "track02.wav", "relative_path": "RJ123456/track02.wav", "is_dir": False},
    ])

    assert [row["relative_path"] for row in rows] == [
        "RJ123456",
        "RJ123456/track01.wav",
        "RJ123456/track02.wav",
    ]


def test_baidu_custom_group_folder_keeps_split_volume_base_consistent(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_name": "铁大哥人妻",
            "custom_extract_password": "southplus",
            "custom_group_folder": True,
            "custom_file_names": {
                "fs-z01": {"custom_name": "铁大哥人妻"},
                "fs-z02": {"custom_name": "铁大哥人妻"},
                "fs-zip": {"custom_name": "铁大哥人妻"},
            },
        },
        [
            {"fs_id": "fs-z01", "name": "铁大哥人妻-z01", "relative_path": "铁大哥人妻-z01"},
            {"fs_id": "fs-z02", "name": "铁大哥人妻-z02", "relative_path": "铁大哥人妻-z02"},
            {"fs_id": "fs-zip", "name": "铁大哥人妻.zip", "relative_path": "铁大哥人妻.zip"},
            {"fs_id": "fs-note", "name": "readme.txt", "relative_path": "readme.txt"},
        ],
    )

    volume_rows = rows[:3]
    note_row = rows[3]
    assert [row["name"] for row in volume_rows] == ["铁大哥人妻.z01", "铁大哥人妻.z02", "铁大哥人妻.zip"]
    assert [os.path.basename(row["relative_path"]) for row in volume_rows] == ["铁大哥人妻.z01", "铁大哥人妻.z02", "铁大哥人妻.zip"]
    assert all(os.path.dirname(row["relative_path"]) == "铁大哥人妻（southplus）" for row in volume_rows)
    assert all(row["custom_group_folder_applied"] is True for row in volume_rows)
    assert note_row["relative_path"] == "readme.txt"
    assert not note_row.get("custom_group_folder_applied")


def test_baidu_custom_group_folder_does_not_create_subdir_when_only_selected_volumes(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_name": "铁大哥人妻",
            "custom_extract_password": "southplus",
            "custom_group_folder": True,
            "custom_file_names": {
                "fs-z01": {"custom_name": "铁大哥人妻"},
                "fs-z02": {"custom_name": "铁大哥人妻"},
                "fs-zip": {"custom_name": "铁大哥人妻"},
            },
        },
        [
            {"fs_id": "fs-z01", "name": "铁大哥人妻-z01", "relative_path": "铁大哥人妻-z01"},
            {"fs_id": "fs-z02", "name": "铁大哥人妻-z02", "relative_path": "铁大哥人妻-z02"},
            {"fs_id": "fs-zip", "name": "铁大哥人妻.zip", "relative_path": "铁大哥人妻.zip"},
        ],
    )

    assert [row["relative_path"] for row in rows] == ["铁大哥人妻.z01", "铁大哥人妻.z02", "铁大哥人妻.zip"]
    assert all(not row.get("custom_group_folder_applied") for row in rows)


def test_baidu_custom_file_names_apply_to_multi_file_share(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_file_names": {
                "fs-001": {
                    "custom_name": "RJ01609723.7z",
                    "custom_extract_password": "southplus@mzh1051",
                },
                "folder/RJ01609723.7z.002": {
                    "custom_name": "RJ01609723.7z",
                },
            },
        },
        [
            {
                "fs_id": "fs-001",
                "name": "RJ01609723.7z.001",
                "relative_path": "folder/RJ01609723.7z.001",
                "original_relative_path": "folder/RJ01609723.7z.001",
            },
            {
                "fs_id": "fs-002",
                "name": "RJ01609723.7z.002",
                "relative_path": "folder/RJ01609723.7z.002",
                "original_relative_path": "folder/RJ01609723.7z.002",
            },
        ],
    )

    assert rows[0]["name"] == "RJ01609723.7z（southplus@mzh1051）.001"
    assert rows[0]["relative_path"] == os.path.join("folder", "RJ01609723.7z（southplus@mzh1051）.001")
    assert rows[0]["custom_file_rename_applied"] is True
    assert rows[1]["name"] == "RJ01609723.7z.002"
    assert rows[1]["relative_path"] == os.path.join("folder", "RJ01609723.7z.002")
    assert rows[1]["custom_file_rename_applied"] is True


def test_baidu_custom_file_names_dedupe_split_volume_suffix(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_file_names": {
                "fs-001": {"custom_name": "RJ01618696.7z.001"},
                "fs-002": {"custom_name": "RJ01618696.7z.002"},
                "fs-003": {"custom_name": "RJ01618696.7z.003"},
                "fs-004": {"custom_name": "RJ01618696.7z.004"},
            },
        },
        [
            {"fs_id": "fs-001", "name": "RJ01618696.7z.001", "relative_path": "RJ01618696.7z.001"},
            {"fs_id": "fs-002", "name": "RJ01618696.7z.002", "relative_path": "RJ01618696.7z.002"},
            {"fs_id": "fs-003", "name": "RJ01618696.7z.003", "relative_path": "RJ01618696.7z.003"},
            {"fs_id": "fs-004", "name": "RJ01618696.7z.004", "relative_path": "RJ01618696.7z.004"},
        ],
    )

    assert [row["name"] for row in rows] == [
        "RJ01618696.7z.001",
        "RJ01618696.7z.002",
        "RJ01618696.7z.003",
        "RJ01618696.7z.004",
    ]
    assert all(".7z.002.7z.002" not in row["relative_path"] for row in rows)


def test_baidu_custom_file_names_dedupe_first_volume_name_for_all_parts(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    rows = service._apply_custom_download_name_to_rows(
        {
            "custom_file_names": {
                "fs-001": {"custom_name": "RJ01618696.7z.001"},
                "fs-002": {"custom_name": "RJ01618696.7z.001"},
            },
        },
        [
            {"fs_id": "fs-001", "name": "RJ01618696.7z.001", "relative_path": "RJ01618696.7z.001"},
            {"fs_id": "fs-002", "name": "RJ01618696.7z.002", "relative_path": "RJ01618696.7z.002"},
        ],
    )

    assert [row["name"] for row in rows] == [
        "RJ01618696.7z.001",
        "RJ01618696.7z.002",
    ]


def test_baidu_filter_preview_selection_merges_custom_file_names():
    service = BaiduNetdiskService()

    preview = {
        "items": [{
            "ok": True,
            "selection_key": "baidu:item",
            "share_id": "share-id",
            "share_url": "https://pan.baidu.com/s/share?pwd=0402",
            "filename": "RJ01609723",
            "share_files": [{
                "name": "RJ01609723.7z.001",
                "relative_path": "RJ01609723/RJ01609723.7z.001",
                "path": "/RJ01609723/RJ01609723.7z.001",
                "fs_id": "fs-001",
            }],
        }],
    }

    filtered = service.filter_preview_selection(
        preview,
        selected_items=[{
            "selection_key": "baidu:item",
            "custom_file_names": {
                "fs-001": {
                    "custom_name": "RJ01609723.7z",
                    "custom_extract_password": "southplus@mzh1051",
                },
            },
        }],
    )

    assert filtered["items"][0]["custom_file_names"]["fs-001"]["custom_name"] == "RJ01609723.7z"
    assert filtered["items"][0]["custom_file_names"]["fs-001"]["custom_extract_password"] == "southplus@mzh1051"


def test_baidu_filter_preview_selection_keeps_share_file_custom_password(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.extract = type("ExtractConfig", (), {
        "filename_password_sniff_templates": ["{name}（{password}）"],
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    preview = {
        "items": [{
            "ok": True,
            "selection_key": "baidu:item",
            "share_id": "share-id",
            "share_url": "https://pan.baidu.com/s/share?pwd=0402",
            "filename": "RJ01609723",
            "share_files": [{
                "name": "RJ01609723.7z.001",
                "relative_path": "RJ01609723/RJ01609723.7z.001",
                "path": "/RJ01609723/RJ01609723.7z.001",
                "fs_id": "fs-001",
            }],
        }],
    }

    filtered = service.filter_preview_selection(
        preview,
        selected_items=[{
            "selection_key": "baidu:item",
            "share_files": [{
                "name": "RJ01609723.7z.001",
                "relative_path": "RJ01609723/RJ01609723.7z.001",
                "path": "/RJ01609723/RJ01609723.7z.001",
                "fs_id": "fs-001",
                "custom_name": "RJ01609723.7z",
                "custom_extract_password": "southplus@mzh1051",
            }],
        }],
    )

    item = filtered["items"][0]
    assert item["share_files"][0]["custom_extract_password"] == "southplus@mzh1051"
    assert item["custom_file_names"]["fs-001"]["custom_extract_password"] == "southplus@mzh1051"

    rows = service._apply_custom_download_name_to_rows(
        item,
        [{
            "fs_id": "fs-001",
            "name": "RJ01609723.7z.001",
            "relative_path": "RJ01609723/RJ01609723.7z.001",
            "original_relative_path": "RJ01609723/RJ01609723.7z.001",
        }],
    )

    assert rows[0]["name"] == "RJ01609723.7z（southplus@mzh1051）.001"
    assert rows[0]["relative_path"] == os.path.join("RJ01609723", "RJ01609723.7z（southplus@mzh1051）.001")


@pytest.mark.asyncio
async def test_baidu_web_transfer_uses_decoded_sekey(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_make_web_logid", lambda _cookie: "log-id")
    monkeypatch.setattr(service, "_make_dp_logid", lambda: "dp-log-id")
    calls = []

    async def fake_form_json(url, cookie, *, data=None, referer="", timeout=20, use_requests=False):
        calls.append({
            "url": url,
            "cookie": cookie,
            "data": data,
            "referer": referer,
            "timeout": timeout,
            "use_requests": use_requests,
        })
        query = parse_qs(urlparse(url).query)
        assert url.startswith("https://pan.baidu.com/share/transfer?")
        assert query["shareid"] == ["67834288070"]
        assert query["from"] == ["1101216675428"]
        assert query["sekey"] == ["uzjNNR+OtCzO+7jt7ksocH7T8vkGYZqURizMmjySHhE="]
        assert query["web"] == ["1"]
        assert query["app_id"] == ["250528"]
        assert query["clienttype"] == ["0"]
        assert query["ondup"] == ["overwrite"]
        assert data == {"fsidlist": "[970978578267394]", "path": "/km_test"}
        assert referer == "https://pan.baidu.com/share/init?surl=3EU1GlLvUULM43mkqhoZxA"
        assert timeout == 60
        assert use_requests is True
        return {
            "errno": 0,
            "info": [{"errno": 0, "fsid": 970978578267394, "path": "/RJ01534331.rar"}],
        }

    monkeypatch.setattr(service, "_fetch_form_json", fake_form_json)

    result = await service._transfer_share_item_by_web(
        {
            "fs_id": "970978578267394",
            "share_numeric_id": "67834288070",
            "share_uk": "1101216675428",
            "randsk": "uzjNNR%2BOtCzO%2B7jt7ksocH7T8vkGYZqURizMmjySHhE%3D",
            "shorturl": "13EU1GlLvUULM43mkqhoZxA",
            "bdstoken": "",
        },
        "BDUSS=test; BDCLND=uzjNNR%2BOtCzO%2B7jt7ksocH7T8vkGYZqURizMmjySHhE%3D",
        "/km_test",
        share_url="https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
        pass_code="38a2",
    )

    assert result["errno"] == 0
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_baidu_web_transfer_retries_ssl_eof_with_fresh_logids(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.transfer_retry_count = 4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    web_logids = iter(["web-1", "web-2", "web-3"])
    dp_logids = iter(["dp-1", "dp-2", "dp-3"])
    monkeypatch.setattr(service, "_make_web_logid", lambda _cookie: next(web_logids))
    monkeypatch.setattr(service, "_make_dp_logid", lambda: next(dp_logids))
    monkeypatch.setattr(service, "_wait_baidu_transfer_retry", lambda *_args, **_kwargs: asyncio.sleep(0))
    calls = []

    async def fake_form_json(url, *_args, **_kwargs):
        query = parse_qs(urlparse(url).query)
        calls.append((query["logid"][0], query["dp-logid"][0]))
        if len(calls) < 3:
            raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return {"errno": 0, "info": [{"errno": 0}]}

    monkeypatch.setattr(service, "_fetch_form_json", fake_form_json)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-retry-test",
    )
    row = {
        "name": "RJ01449225.7z",
        "fs_id": "970978578267394",
        "share_numeric_id": "67834288070",
        "share_uk": "1101216675428",
        "randsk": "rand-sk",
        "shorturl": "13EU1GlLvUULM43mkqhoZxA",
        "status": "downloading",
    }

    result = await service._transfer_share_item_with_retry(
        task,
        row,
        "BDUSS=test; BDCLND=rand-sk",
        "/km_test",
        share_url="https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA",
        pass_code="",
        download_files=[row],
        started=time.monotonic(),
        cancel_event=asyncio.Event(),
    )

    assert result["errno"] == 0
    assert calls == [("web-1", "dp-1"), ("web-2", "dp-2"), ("web-3", "dp-3")]
    assert row["transfer_attempt"] == 3
    assert row["transfer_status"] == "completed"


@pytest.mark.asyncio
async def test_baidu_web_transfer_business_error_is_not_retried(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.transfer_retry_count = 4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    calls = 0

    async def fake_form_json(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"errno": -9, "errmsg": "分享文件不存在"}

    monkeypatch.setattr(service, "_fetch_form_json", fake_form_json)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-business-error-test",
    )
    row = {
        "name": "missing.7z",
        "fs_id": "1",
        "share_numeric_id": "2",
        "share_uk": "3",
        "randsk": "rand-sk",
        "status": "downloading",
    }

    with pytest.raises(BaiduNetdiskError, match="分享文件不存在"):
        await service._transfer_share_item_with_retry(
            task,
            row,
            "BDUSS=test; BDCLND=rand-sk",
            "/km_test",
            share_url="https://pan.baidu.com/s/test",
            pass_code="",
            download_files=[row],
            started=time.monotonic(),
            cancel_event=asyncio.Event(),
        )

    assert calls == 1
    assert row["transfer_status"] == "failed"


@pytest.mark.asyncio
async def test_baidu_web_transfer_is_globally_serialized(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.transfer_max_concurrency = 1
    config.baidu_netdisk.transfer_retry_count = 0
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    active = 0
    max_active = 0

    async def fake_transfer(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"errno": 0}

    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_transfer)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-concurrency-test",
    )
    rows = [{"name": f"RJ{index}.7z", "status": "downloading"} for index in range(8)]

    await asyncio.gather(*[
        service._transfer_share_item_with_retry(
            task,
            row,
            "BDUSS=test",
            f"/km_test_{index}",
            share_url="https://pan.baidu.com/s/test",
            pass_code="",
            download_files=rows,
            started=time.monotonic(),
            cancel_event=asyncio.Event(),
        )
        for index, row in enumerate(rows)
    ])

    assert max_active == 1
    assert all(row["transfer_status"] == "completed" for row in rows)


@pytest.mark.asyncio
async def test_baidu_web_transfer_retry_wait_can_be_cancelled(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.transfer_retry_count = 4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    async def fail_transfer(*_args, **_kwargs):
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setattr(service, "_transfer_share_item_by_web", fail_transfer)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-cancel-test",
    )
    row = {"name": "RJ01449225.7z", "status": "downloading"}
    cancel_event = asyncio.Event()
    transfer_task = asyncio.create_task(service._transfer_share_item_with_retry(
        task,
        row,
        "BDUSS=test",
        "/km_test",
        share_url="https://pan.baidu.com/s/test",
        pass_code="",
        download_files=[row],
        started=time.monotonic(),
        cancel_event=cancel_event,
    ))
    while row.get("transfer_status") != "retrying":
        await asyncio.sleep(0)
    cancel_event.set()

    with pytest.raises(asyncio.CancelledError):
        await transfer_task


@pytest.mark.asyncio
async def test_baidu_web_transfer_accepts_confirmed_remote_file_after_ssl_eof(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.transfer_retry_count = 4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    calls = 0

    async def fail_transfer(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    async def confirm_transferred():
        return True

    monkeypatch.setattr(service, "_transfer_share_item_by_web", fail_transfer)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-confirm-test",
    )
    row = {"name": "RJ01449225.7z", "status": "downloading"}

    result = await service._transfer_share_item_with_retry(
        task,
        row,
        "BDUSS=test",
        "/km_test",
        share_url="https://pan.baidu.com/s/test",
        pass_code="",
        download_files=[row],
        started=time.monotonic(),
        cancel_event=asyncio.Event(),
        confirm_transferred=confirm_transferred,
    )

    assert calls == 1
    assert result["confirmed_after_error"] is True
    assert row["transfer_confirmed_after_error"] is True
    assert any("已确认远端文件名称和大小一致" in item["message"] for item in task.task_metadata["progress_log"])


@pytest.mark.asyncio
async def test_baidu_remote_transfer_confirmation_requires_matching_size(monkeypatch, tmp_path):
    service = BaiduNetdiskService()

    async def fake_run(args, *, on_output=None, **_kwargs):
        assert args[1:] == ["ls", "/km_test"]
        on_output("- 123456 RJ01449225.7z")

    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-size-confirm-test",
    )

    matched = await service._confirm_remote_temporary_transfer_file(
        "BaiduPCS-Go",
        "/km_test",
        "RJ01449225.7z",
        123456,
        env={},
        log_path=str(tmp_path / "pcsgo.log"),
        task=task,
        cancel_event=asyncio.Event(),
    )
    mismatched = await service._confirm_remote_temporary_transfer_file(
        "BaiduPCS-Go",
        "/km_test",
        "RJ01449225.7z",
        654321,
        env={},
        log_path=str(tmp_path / "pcsgo.log"),
        task=task,
        cancel_event=asyncio.Event(),
    )

    assert matched is True
    assert mismatched is False


@pytest.mark.asyncio
async def test_baidu_remote_transfer_confirmation_prefers_exact_web_list_size(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    pcsgo_calls = []

    async def fake_fetch(url, *_args, **_kwargs):
        assert url.startswith("https://pan.baidu.com/api/list?")
        assert parse_qs(urlparse(url).query)["dir"] == ["/km_test"]
        return {"errno": 0, "list": [{"server_filename": "RJ01449225.7z", "size": 123456}]}

    async def fake_run(*_args, **_kwargs):
        pcsgo_calls.append(True)

    monkeypatch.setattr(service, "_fetch_json", fake_fetch)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run)
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-transfer-web-list-confirm-test",
    )

    matched = await service._confirm_remote_temporary_transfer_file(
        "BaiduPCS-Go",
        "/km_test",
        "RJ01449225.7z",
        123456,
        row={"bdstoken": "token"},
        cookie="BDUSS=test",
        env={},
        log_path=str(tmp_path / "pcsgo.log"),
        task=task,
        cancel_event=asyncio.Event(),
    )

    assert matched is True
    assert pcsgo_calls == []


def test_baidu_transfer_error_sanitizes_sensitive_query_parameters():
    service = BaiduNetdiskService()
    message = (
        "https://pan.baidu.com/share/transfer?sekey=secret&logid=log-secret&dp-logid=dp-secret "
        "randsk=rand-secret bdstoken=token-secret"
    )

    sanitized = service._sanitize_error(message)

    assert "secret" not in sanitized
    assert "sekey=***" in sanitized
    assert "logid=***" in sanitized
    assert "dp-logid=***" in sanitized
    assert "randsk=***" in sanitized
    assert "bdstoken=***" in sanitized


@pytest.mark.asyncio
async def test_baidu_download_uses_web_transfer_before_pcsgo_download(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_test")
    transfer_calls = []
    pcsgo_commands = []

    async def fake_transfer(row, cookie, remote_tmp_dir, *, share_url, pass_code=""):
        transfer_calls.append({
            "row": dict(row),
            "cookie": cookie,
            "remote_tmp_dir": remote_tmp_dir,
            "share_url": share_url,
            "pass_code": pass_code,
        })
        return {"errno": 0}

    async def fake_run_pcsgo(args, *, env, log_path, task, cancel_event, ignore_task_cancel=False, on_output=None, abort_check=None, heartbeat_message="", max_runtime_seconds=0):
        pcsgo_commands.append(tuple(args[1:]))
        if len(args) > 1 and args[1] == "download":
            savedir = args[args.index("--saveto") + 1]
            Path(savedir).mkdir(parents=True, exist_ok=True)
            (Path(savedir) / "RJ01534331.rar").write_bytes(b"rar")
            if on_output:
                on_output("下载中 3B/3B 100% 1B/s")

    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_transfer)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_pcsgo)

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-web-transfer-test",
    )
    row = {
        "name": "RJ01534331.rar",
        "relative_path": "RJ01534331.rar",
        "share_url": "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
        "pass_code": "38a2",
        "fs_id": "970978578267394",
        "share_numeric_id": "67834288070",
        "share_uk": "1101216675428",
        "randsk": "randsk",
        "total": 3,
        "size": 3,
        "status": "downloading",
        "progress": 0,
        "downloaded": 0,
    }

    await service._download_share_item_via_temporary_transfer(
        task,
        str(tmp_path / "staging"),
        str(tmp_path / "staging" / "RJ01534331.rar"),
        row,
        [row],
        time.monotonic(),
        asyncio.Event(),
    )

    assert transfer_calls == [{
        "row": {
            "name": "RJ01534331.rar",
            "relative_path": "RJ01534331.rar",
            "share_url": "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
            "pass_code": "38a2",
            "fs_id": "970978578267394",
            "share_numeric_id": "67834288070",
            "share_uk": "1101216675428",
            "randsk": "randsk",
            "total": 3,
            "size": 3,
            "status": "downloading",
            "progress": 0,
            "downloaded": 0,
        },
        "cookie": "BDUSS=test; STOKEN=test; BDCLND=randsk",
        "remote_tmp_dir": "/km_test",
        "share_url": "https://pan.baidu.com/s/13EU1GlLvUULM43mkqhoZxA?pwd=38a2",
        "pass_code": "38a2",
    }]
    assert not any(command and command[0] == "transfer" for command in pcsgo_commands)
    assert any(command and command[0] == "download" for command in pcsgo_commands)
    assert (tmp_path / "staging" / "RJ01534331.rar").read_bytes() == b"rar"


@pytest.mark.asyncio
async def test_baidu_low_speed_refresh_reuses_existing_pcsgo_checkpoint(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    config.baidu_netdisk.vip_type = 2
    config.baidu_netdisk.low_speed_refresh_enabled = True
    config.baidu_netdisk.low_speed_threshold_mbps = 3
    config.baidu_netdisk.low_speed_duration_seconds = 180
    config.baidu_netdisk.low_speed_refresh_limit = 2
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_20260712_190054_9ae558")

    transfer_calls = []
    download_savedirs = []
    download_abort_checks = []

    async def fake_transfer(row, cookie, remote_tmp_dir, *, share_url, pass_code=""):
        transfer_calls.append(remote_tmp_dir)
        return {"errno": 0}

    async def fake_run_pcsgo(
        args,
        *,
        env,
        log_path,
        task,
        cancel_event,
        ignore_task_cancel=False,
        on_output=None,
        abort_check=None,
        heartbeat_message="",
        max_runtime_seconds=0,
    ):
        if args[1] != "download":
            return
        savedir = args[args.index("--saveto") + 1]
        download_savedirs.append(savedir)
        download_abort_checks.append(abort_check)
        checkpoint = Path(savedir) / "RJ01648657.7z.BaiduPCS-Go-downloading"
        if len(download_savedirs) == 1:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_bytes(b"existing-checkpoint")
            if on_output:
                on_output("下载中 600MiB/1GiB 58% 2MiB/s")
            raise BaiduNetdiskLowSpeedError(2 * 1024 * 1024, 180, 600 * 1024 * 1024)
        if len(download_savedirs) == 2:
            assert checkpoint.read_bytes() == b"existing-checkpoint"
            if on_output:
                on_output("下载中 50MiB/1GiB 4% 1.5MiB/s")
            raise BaiduNetdiskLowSpeedError(int(1.5 * 1024 * 1024), 180, 650 * 1024 * 1024)

        assert checkpoint.read_bytes() == b"existing-checkpoint"
        completed = Path(savedir) / "RJ01648657.7z"
        completed.write_bytes(b"completed")

    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_transfer)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_pcsgo)

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-low-speed-refresh-test",
    )
    row = {
        "name": "RJ01648657.7z",
        "relative_path": "RJ01648657.7z",
        "share_url": "https://pan.baidu.com/s/test?pwd=0402",
        "pass_code": "0402",
        "fs_id": "732325025154301",
        "share_numeric_id": "60130084160",
        "share_uk": "1635081079",
        "randsk": "rand-sk",
        "total": 1024 * 1024 * 1024,
        "size": 1024 * 1024 * 1024,
        "status": "downloading",
        "progress": 0,
        "downloaded": 0,
    }
    target_path = tmp_path / "staging" / "RJ01648657.7z"

    await service._download_share_item_via_temporary_transfer(
        task,
        str(tmp_path / "staging"),
        str(target_path),
        row,
        [row],
        time.monotonic(),
        asyncio.Event(),
    )

    assert transfer_calls == ["/km_20260712_190054_9ae558"]
    assert len(download_savedirs) == 3
    assert len(set(download_savedirs)) == 1
    assert download_abort_checks[0] is not None
    assert download_abort_checks[1] is not None
    assert download_abort_checks[2] is None
    assert target_path.read_bytes() == b"completed"
    assert row["link_refresh_attempt"] == 2
    assert row["checkpoint_bytes"] == 650 * 1024 * 1024
    assert row["link_refresh_status"] == "completed"
    assert any("复用旧断点" in item["message"] for item in task.task_metadata["progress_log"])


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


def test_baidu_pcsgo_resume_progress_keeps_checkpoint_offset(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: DummyConfig())
    checkpoint = 600 * 1024 * 1024
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-resume-progress-test",
    )
    row = {
        "name": "RJ01648657.7z",
        "relative_path": "RJ01648657.7z",
        "status": "downloading",
        "progress": 58,
        "downloaded": checkpoint,
        "total": 1024 * 1024 * 1024,
        "size": 1024 * 1024 * 1024,
        "speed_bytes_per_sec": 0,
    }

    service._update_pcsgo_transfer_progress(
        task,
        row,
        [row],
        time.monotonic() - 5,
        "下载中 10MiB/1GiB 1% 4MiB/s",
        {
            "last_emit_at": 0.0,
            "last_log_at": 0.0,
            "resume_checkpoint_bytes": checkpoint,
        },
    )

    assert row["downloaded"] == checkpoint + 10 * 1024 * 1024
    assert row["progress"] >= 59


def test_baidu_low_speed_window_uses_downloaded_byte_delta():
    service = BaiduNetdiskService()
    row = {
        "downloaded": 100 * 1024 * 1024,
        "total": 1024 * 1024 * 1024,
    }
    state = {}

    assert service._check_baidu_low_speed(
        row,
        state,
        threshold_bytes=3 * 1024 * 1024,
        duration_seconds=180,
        now=0,
    ) is None

    row["downloaded"] += 2 * 1024 * 1024 * 180
    error = service._check_baidu_low_speed(
        row,
        state,
        threshold_bytes=3 * 1024 * 1024,
        duration_seconds=180,
        now=180,
    )

    assert isinstance(error, BaiduNetdiskLowSpeedError)
    assert error.average_speed_bytes == 2 * 1024 * 1024
    assert error.checkpoint_bytes == row["downloaded"]
    assert row["low_speed_window_bytes_per_sec"] == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_baidu_pcsgo_command_aborts_only_current_process_for_low_speed(tmp_path):
    service = BaiduNetdiskService()
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-low-speed-process-abort-test",
    )
    checks = 0

    def abort_check():
        nonlocal checks
        checks += 1
        if checks >= 2:
            return BaiduNetdiskLowSpeedError(1024 * 1024, 180, 256 * 1024 * 1024)
        return None

    started = time.monotonic()
    with pytest.raises(BaiduNetdiskLowSpeedError):
        await service._run_baidu_pcs_go_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=os.environ.copy(),
            log_path=str(tmp_path / "baidupcs-go.log"),
            task=task,
            cancel_event=asyncio.Event(),
            abort_check=abort_check,
        )

    assert time.monotonic() - started < 10
    assert not task.is_cancelled()


def test_baidu_upload_args_and_remote_dir_are_normalized(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.upload_max_parallel = 8
    config.baidu_netdisk.upload_max_load = 6
    config.baidu_netdisk.upload_conflict_policy = "rsync"
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    remote_dir = service._join_remote_dir("KikoeruManager//备份", "RJ:001/../今日")
    args = service._baidu_pcs_go_upload_args("BaiduPCS-Go", ["D:/ASMR/RJ001"], remote_dir, service._upload_conflict_policy("overwrite"))

    assert remote_dir == "/KikoeruManager/备份/RJ_001/今日"
    assert args == [
        "BaiduPCS-Go",
        "upload",
        "-p",
        "8",
        "-l",
        "6",
        "--policy",
        "overwrite",
        "D:/ASMR/RJ001",
        "/KikoeruManager/备份/RJ_001/今日",
    ]
    assert service._upload_conflict_policy("bad") == "rsync"


def test_baidu_pcsgo_config_cookie_fields_are_patched(tmp_path):
    service = BaiduNetdiskService()
    config_dir = tmp_path / "pcsgo"
    config_dir.mkdir()
    config_path = config_dir / "pcs_config.json"
    config_path.write_text(json.dumps({
        "baidu_user_list": [{
            "bduss": "old-bduss",
            "stoken": "",
            "ptoken": "",
            "baiduid": "",
            "cookies": "BDUSS=old-bduss",
        }]
    }), encoding="utf-8")

    service._patch_baidu_pcsgo_config_cookie_fields(
        str(config_dir),
        "BDUSS=bduss-value; STOKEN=stoken-value; PTOKEN=ptoken-value; BAIDUID=baiduid-value; BDCLND=rand-sk",
    )

    row = json.loads(config_path.read_text(encoding="utf-8"))["baidu_user_list"][0]
    assert row["bduss"] == "bduss-value"
    assert row["stoken"] == "stoken-value"
    assert row["ptoken"] == "ptoken-value"
    assert row["baiduid"] == "baiduid-value"
    assert row["bdclnd"] == "rand-sk"
    assert row["cookies"] == "BDUSS=bduss-value; STOKEN=stoken-value; PTOKEN=ptoken-value; BAIDUID=baiduid-value; BDCLND=rand-sk"


def test_baidu_pcsgo_cookie_config_is_written_without_login(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    config.baidu_netdisk.account_uk = "957180921"
    config.baidu_netdisk.account_name = "tester"
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    config_path = service._write_baidu_pcsgo_cookie_config(
        str(tmp_path / "pcsgo"),
        "BDUSS=bduss-value; STOKEN_BFESS=stoken-bfess; PTOKEN=ptoken-value; BAIDUID_BFESS=baiduid-bfess; BDCLND=rand-sk",
        workdir="/km_test",
    )

    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    row = data["baidu_user_list"][0]
    assert data["baidu_active_uid"] == 957180921
    assert row["name"] == "tester"
    assert row["bduss"] == "bduss-value"
    assert row["stoken"] == "stoken-bfess"
    assert row["ptoken"] == "ptoken-value"
    assert row["baiduid"] == "baiduid-bfess"
    assert row["bdclnd"] == "rand-sk"
    assert row["workdir"] == "/km_test"
    assert row["cookies"] == "BDUSS=bduss-value; STOKEN_BFESS=stoken-bfess; PTOKEN=ptoken-value; BAIDUID_BFESS=baiduid-bfess; BDCLND=rand-sk"
    assert data["enable_https"] is True
    assert data["no_check"] is True
    assert data["ignore_illegal"] is True


@pytest.mark.asyncio
async def test_baidu_password_login_reads_pcsgo_cookie_and_tests_account(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    command_log = []

    async def fake_run_login(args, *, env, timeout=75):
        command_log.append(tuple(args[1:]))
        config_dir = Path(env["BAIDUPCS_GO_CONFIG_DIR"])
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "pcs_config.json").write_text(json.dumps({
            "baidu_user_list": [{
                "bduss": "bduss-value",
                "stoken": "stoken-value",
                "BAIDUID": "baiduid-value",
            }]
        }), encoding="utf-8")
        return 0, "登录成功"

    async def fake_test_account(cookie, *, persist=False, allow_quota_failure=False):
        assert cookie == "BDUSS=bduss-value; STOKEN=stoken-value; BAIDUID=baiduid-value"
        assert persist is True
        assert allow_quota_failure is True
        return {
            "success": True,
            "message": "百度账号检测成功",
            "account": {
                "name": "tester",
                "configured": True,
                "ready": True,
            },
        }

    monkeypatch.setattr(service, "_run_baidu_pcs_go_login_command", fake_run_login)
    monkeypatch.setattr(service, "test_account", fake_test_account)

    result = await service.login_with_password("user@example.com", "secret", persist=True)

    assert result["success"] is True
    assert result["account"]["login_method"] == "password"
    assert result["cookie_names"] == ["BDUSS", "STOKEN", "BAIDUID"]
    assert command_log == [("login", "--username=user@example.com", "--password=secret")]


@pytest.mark.asyncio
async def test_baidu_account_quota_failure_keeps_cached_quota_and_vip_expire(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.quota_bytes = 10 * 1024**4
    config.baidu_netdisk.used_bytes = 4 * 1024**4
    config.baidu_netdisk.vip_expire_at = 1780000000
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    async def fake_fetch_account(_cookie):
        return {
            "name": "tester",
            "vip_type": 2,
            "vip_label": "SVIP",
            "vip_expire_at": 0,
        }

    async def fake_fetch_quota(_cookie):
        raise RuntimeError("HTTP 400")

    monkeypatch.setattr(service, "_fetch_account_by_web", fake_fetch_account)
    monkeypatch.setattr(service, "_fetch_quota_by_web", fake_fetch_quota)

    result = await service.test_account("BDUSS=test", persist=False, allow_quota_failure=True)

    assert result["success"] is True
    assert result["account"]["quota_bytes"] == 10 * 1024**4
    assert result["account"]["used_bytes"] == 4 * 1024**4
    assert result["account"]["vip_expire_at"] == 1780000000
    assert "warning" in result


@pytest.mark.asyncio
async def test_baidu_refresh_account_status_allows_quota_failure(monkeypatch):
    service = BaiduNetdiskService()
    calls = []

    async def fake_test_account(cookie, *, persist=False, allow_quota_failure=False):
        calls.append({
            "cookie": cookie,
            "persist": persist,
            "allow_quota_failure": allow_quota_failure,
        })
        return {
            "success": True,
            "message": "百度账号检测成功，容量刷新失败: HTTP 400",
            "warning": "容量刷新失败: HTTP 400",
            "account": {
                "name": "tester",
                "configured": True,
                "ready": True,
            },
        }

    monkeypatch.setattr(service, "test_account", fake_test_account)

    result = await service.refresh_account_status()

    assert calls == [{
        "cookie": "",
        "persist": True,
        "allow_quota_failure": True,
    }]
    assert result["success"] is True
    assert result["warning"] == "容量刷新失败: HTTP 400"
    assert result["message"] == "百度账号状态已刷新，容量接口暂不可用，已保留本地容量缓存"


def test_baidu_parse_pcsgo_quota_output():
    service = BaiduNetdiskService()

    result = service._parse_pcsgo_quota_output("已使用: 1.5TB\n总空间: 5.0TB")

    assert result["used_bytes"] == int(1.5 * 1024**4)
    assert result["quota_bytes"] == 5 * 1024**4
    assert result["vip_expire_at"] == 0


@pytest.mark.asyncio
async def test_baidu_quota_falls_back_to_pcsgo_when_web_api_fails(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    command_log = []

    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")

    async def fake_fetch_json(_url, _cookie, timeout=20, referer=""):
        raise RuntimeError("HTTP Error 400: Bad Request")

    async def fake_run_pcsgo(args, *, env, timeout=75):
        command_log.append(tuple(args[1:]))
        assert env["BAIDUPCS_GO_CONFIG_DIR"].startswith(str(tmp_path / "temp"))
        if args[1] == "quota":
            config_path = Path(env["BAIDUPCS_GO_CONFIG_DIR"]) / "pcs_config.json"
            row = json.loads(config_path.read_text(encoding="utf-8"))["baidu_user_list"][0]
            assert row["bduss"] == "test"
            assert row["cookies"] == "BDUSS=test"
            return 0, "已使用: 2.0TB\n总空间: 8.0TB"
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(service, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_login_command", fake_run_pcsgo)

    result = await service._fetch_quota_by_web("BDUSS=test")

    assert result["used_bytes"] == 2 * 1024**4
    assert result["quota_bytes"] == 8 * 1024**4
    assert command_log == [("quota",)]


def test_baidu_persist_account_keeps_missing_cached_fields(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.account_name = "old-name"
    config.baidu_netdisk.account_netdisk_name = "old-netdisk"
    config.baidu_netdisk.account_avatar_url = "https://old/avatar.jpg"
    config.baidu_netdisk.account_uk = "old-uk"
    config.baidu_netdisk.vip_type = 2
    config.baidu_netdisk.vip_label = "SVIP"
    config.baidu_netdisk.vip_level = "7"
    config.baidu_netdisk.vip_expire_at = 1780000000
    config.baidu_netdisk.quota_bytes = 10 * 1024**4
    config.baidu_netdisk.used_bytes = 4 * 1024**4
    config.model_dump = lambda: {
        "baidu_netdisk": {
            "enabled": True,
            "cookie": "BDUSS=old",
            "account_name": config.baidu_netdisk.account_name,
            "account_netdisk_name": config.baidu_netdisk.account_netdisk_name,
            "account_avatar_url": config.baidu_netdisk.account_avatar_url,
            "account_uk": config.baidu_netdisk.account_uk,
            "vip_type": config.baidu_netdisk.vip_type,
            "vip_label": config.baidu_netdisk.vip_label,
            "vip_level": config.baidu_netdisk.vip_level,
            "vip_expire_at": config.baidu_netdisk.vip_expire_at,
            "quota_bytes": config.baidu_netdisk.quota_bytes,
            "used_bytes": config.baidu_netdisk.used_bytes,
            "account_cached_at": 1710000000,
        }
    }
    saved = {}

    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr("app.core.baidu_netdisk_service.save_config", lambda data: saved.update(data))

    service._persist_account("BDUSS=new", {
        "name": "new-name",
        "avatar_url": "https://new/avatar.jpg",
        "configured": True,
        "ready": True,
        "cached_at": 1780634000,
    })

    cfg = saved["baidu_netdisk"]
    assert cfg["enabled"] is True
    assert cfg["cookie"] == "BDUSS=new"
    assert cfg["account_name"] == "new-name"
    assert cfg["account_avatar_url"] == "https://new/avatar.jpg"
    assert cfg["account_netdisk_name"] == "old-netdisk"
    assert cfg["account_uk"] == "old-uk"
    assert cfg["vip_type"] == 2
    assert cfg["vip_label"] == "SVIP"
    assert cfg["vip_level"] == "7"
    assert cfg["vip_expire_at"] == 1780000000
    assert cfg["quota_bytes"] == 10 * 1024**4
    assert cfg["used_bytes"] == 4 * 1024**4
    assert cfg["account_cached_at"] == 1780634000


@pytest.mark.asyncio
async def test_baidu_cached_account_without_bduss_is_not_ready(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.cookie = "BDCLND=randsk"
    config.baidu_netdisk.enabled = True
    config.baidu_netdisk.account_name = "cached-name"
    config.baidu_netdisk.vip_type = 2
    config.baidu_netdisk.vip_label = "SVIP"
    config.baidu_netdisk.quota_bytes = 10 * 1024**4
    config.baidu_netdisk.used_bytes = 9 * 1024**4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    account = service.account_status()
    health = await service.health()

    assert account["name"] == "cached-name"
    assert account["configured"] is False
    assert account["ready"] is False
    assert account["login_cookie_valid"] is False
    assert account["quota_bytes"] == 10 * 1024**4
    assert health["ok"] is False
    assert "BDUSS" in health["message"]


def test_baidu_share_download_rejects_cookie_without_bduss(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.cookie = "BDCLND=randsk"
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    with pytest.raises(ValueError, match="BDUSS"):
        service._share_download_cookie({"randsk": "fresh-randsk"})


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
    config.baidu_netdisk.max_download_load = 3
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    command_log = []
    state = {}
    written_config = {}
    transfer_calls = []
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
        abort_check=None,
        heartbeat_message="",
        max_runtime_seconds=0,
    ):
        command_log.append({
            "args": tuple(args[1:]),
            "ignore_task_cancel": ignore_task_cancel,
            "max_runtime_seconds": max_runtime_seconds,
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
        if command in {"cd", "mkdir", "rm", "transfer"}:
            return
        raise AssertionError(f"unexpected command: {args}")

    original_write_config = service._write_baidu_pcsgo_cookie_config

    def capture_write_config(config_dir, cookie, *, workdir="/"):
        config_path = original_write_config(config_dir, cookie, workdir=workdir)
        written_config.update(json.loads(Path(config_path).read_text(encoding="utf-8")))
        return config_path

    async def fake_web_transfer(row, cookie, remote_tmp_dir_arg, *, share_url, pass_code=""):
        transfer_calls.append({
            "fs_id": row.get("fs_id"),
            "cookie": cookie,
            "remote_tmp_dir": remote_tmp_dir_arg,
            "share_url": share_url,
            "pass_code": pass_code,
        })
        return {"errno": 0}

    monkeypatch.setattr(service, "preview_urls", fake_preview_urls)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)
    monkeypatch.setattr(service, "_write_baidu_pcsgo_cookie_config", capture_write_config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: remote_tmp_dir)
    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_web_transfer)

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
    batch_folder = task.task_metadata["download_batch_folder_name"]
    assert re.fullmatch(r"百度网盘_\d{8}_\d{6}", batch_folder)
    assert task.task_metadata["requested_output_folder_name"] == ""
    assert (tmp_path / "downloads" / batch_folder / "狩龙人拉格纳121.mp4").read_bytes() == b"abcdef"
    assert Path(task.task_metadata["final_output_path"]).name == batch_folder
    assert not (tmp_path / "downloads" / ".baidu-netdisk-staging" / "baidu-large-test-task").exists()
    assert task.task_metadata["staging_cleanup"]["success"] is True
    assert task.task_metadata["staging_cleanup"]["cleaned"] is True
    savedir = state["savedir"]
    assert [item["args"] for item in command_log] == [
        ("config", "set", "-savedir", savedir),
        ("config", "set", "-max_parallel", "20"),
        ("config", "set", "-max_download_load", "3"),
        ("config", "set", "-max_download_rate", "0"),
        ("config", "set", "-cache_size", "256KB"),
        ("cd", "/"),
        ("mkdir", remote_tmp_dir),
        ("cd", remote_tmp_dir),
        ("download", remote_tmp_dir, "--saveto", savedir, "--mode", "locate", "-p", "20", "-l", "3", "--retry", "5"),
        ("cd", "/"),
        ("rm", remote_tmp_dir),
    ]
    assert transfer_calls == [{
        "fs_id": "732325025154301",
        "cookie": "BDUSS=test; STOKEN=test; BDCLND=rand-sk",
        "remote_tmp_dir": remote_tmp_dir,
        "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
        "pass_code": "0402",
    }]
    config_user = written_config["baidu_user_list"][0]
    assert config_user["bduss"] == "test"
    assert config_user["stoken"] == "test"
    assert config_user["bdclnd"] == "rand-sk"
    assert config_user["cookies"] == "BDUSS=test; STOKEN=test; BDCLND=rand-sk"
    assert config_user["workdir"] == "/"
    assert all(not item["ignore_task_cancel"] for item in command_log[:-2])
    assert all(item["ignore_task_cancel"] for item in command_log[-2:])
    assert not any(item["args"][0] == "transfer" for item in command_log)
    assert Path(savedir).name == "download"
    assert remote_tmp_dir.startswith("/km_")
    assert len(remote_tmp_dir) <= 32
    assert any("临时转存" in item["message"] for item in task.task_metadata["progress_log"])
    assert any("已删除百度网盘临时转存目录" in item["message"] for item in task.task_metadata["progress_log"])
    assert task.task_metadata["download_files"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_baidu_start_download_records_failed_phase_metric_when_all_files_fail(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.download_root = str(tmp_path / "downloads")
    config.storage.temp_path = str(tmp_path / "temp")
    config.baidu_netdisk.max_download_load = 4
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    recorded = []

    async def fake_preview_urls(*_args, **_kwargs):
        return {
            "items": [{
                "ok": True,
                "selection_key": "baidu:item",
                "filename": "失败文件",
                "share_url": "https://pan.baidu.com/s/fail?pwd=0402",
                "share_id": "fail",
                "share_files": [{
                    "name": "fail.zip",
                    "relative_path": "fail.zip",
                    "path": "/fail.zip",
                    "is_dir": False,
                    "size_bytes": 12,
                    "fs_id": "1001",
                }],
            }],
            "selected_keys": ["baidu:item"],
            "ok_count": 1,
            "success": True,
        }

    async def fake_download_guarded(_task, _staging_dir, row, *_args, **_kwargs):
        row.update({
            "status": "failed",
            "failure_reason": "HTTP 403",
            "downloaded": 3,
        })

    class MetricService:
        async def record_async(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(service, "preview_urls", fake_preview_urls)
    monkeypatch.setattr(service, "_download_share_item_guarded", fake_download_guarded)
    monkeypatch.setattr(
        "app.core.task_phase_metric_service.get_task_phase_metric_service",
        lambda: MetricService(),
    )

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": ["https://pan.baidu.com/s/fail?pwd=0402"],
            "batch_name": "百度失败测试",
            "conflict_policy": "resume",
        },
        status=TaskStatus.PROCESSING,
        task_id="baidu-failed-metric-test",
    )

    with pytest.raises(BaiduNetdiskError, match="HTTP 403"):
        await service.start_download_task(task)

    assert task.task_metadata["download_runtime"]["status"] == "failed"
    assert task.task_metadata["performance_metrics"]["success_count"] == 0
    assert task.task_metadata["performance_metrics"]["failed_count"] == 1
    assert recorded[0]["status"] == "failed"
    assert recorded[0]["phase"] == "baidu_netdisk_download"
    assert recorded[0]["bytes_total"] == 3


def test_baidu_completed_staging_cleanup_rejects_non_task_path(tmp_path):
    service = BaiduNetdiskService()
    download_root = tmp_path / "downloads"
    user_dir = tmp_path / "manual"
    user_file = user_dir / "keep.txt"
    user_dir.mkdir(parents=True)
    user_file.write_text("keep", encoding="utf-8")

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-safe-cleanup-test",
    )

    result = service._cleanup_completed_staging_dir(task, str(user_dir), str(download_root))

    assert result["success"] is False
    assert result["reason"] == "outside_staging_parent"
    assert user_file.read_text(encoding="utf-8") == "keep"


def test_baidu_download_file_concurrency_respects_network_budget(monkeypatch):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.max_download_load = 5
    config.resource_budget = type("ResourceBudget", (), {
        "enabled": True,
        "network_download": 3,
    })()
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    assert service._baidu_download_file_concurrency(8) == 3

    config.resource_budget.network_download = 0
    assert service._baidu_download_file_concurrency(8) == 5


def test_baidu_build_retry_selection_keeps_only_failed_or_incomplete_rows():
    service = BaiduNetdiskService()
    first_item = {
        "ok": True,
        "selection_key": "baidu:first",
        "filename": "第一批",
        "share_url": "https://pan.baidu.com/s/first?pwd=1111",
        "share_files": [
            {"fs_id": "1001", "name": "ok.zip", "relative_path": "ok.zip", "path": "/ok.zip", "size_bytes": 10},
            {"fs_id": "1002", "name": "fail.zip", "relative_path": "fail.zip", "path": "/fail.zip", "size_bytes": 20},
        ],
    }
    second_item = {
        "ok": True,
        "selection_key": "baidu:second",
        "filename": "第二批",
        "share_url": "https://pan.baidu.com/s/second?pwd=2222",
        "share_files": [
            {"fs_id": "2001", "name": "pending.zip", "relative_path": "pending.zip", "path": "/pending.zip", "size_bytes": 30},
        ],
    }
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "raw_selected_items": [first_item, second_item],
            "download_files": [
                {"selection_key": "baidu:first", "fs_id": "1001", "name": "ok.zip", "relative_path": "ok.zip", "status": "completed"},
                {"selection_key": "baidu:second", "fs_id": "2001", "name": "pending.zip", "relative_path": "pending.zip", "status": "downloading", "downloaded": 3, "total": 30},
            ],
            "failed_files": [
                {"selection_key": "baidu:first", "fs_id": "1001", "name": "ok.zip", "relative_path": "ok.zip", "status": "failed", "failure_reason": "old"},
                {"selection_key": "baidu:first", "fs_id": "1002", "name": "fail.zip", "relative_path": "fail.zip", "status": "failed", "failure_reason": "403"},
            ],
        },
    )

    retry_items, retry_keys = service.build_retry_selection_for_task(task)

    assert retry_keys == ["baidu:first", "baidu:second"]
    assert [item["selection_key"] for item in retry_items] == ["baidu:first", "baidu:second"]
    assert [file_item["name"] for file_item in retry_items[0]["share_files"]] == ["fail.zip"]
    assert [file_item["name"] for file_item in retry_items[1]["share_files"]] == ["pending.zip"]


@pytest.mark.asyncio
async def test_baidu_reset_task_for_retry_trims_raw_selection_and_uses_resume():
    service = BaiduNetdiskService()
    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "raw_selected_items": [
                {
                    "ok": True,
                    "selection_key": "baidu:all",
                    "filename": "整批",
                    "share_url": "https://pan.baidu.com/s/all?pwd=1111",
                    "bdstoken": "secret-token",
                    "randsk": "secret-randsk",
                    "share_files": [
                        {"fs_id": "1001", "name": "ok.zip", "relative_path": "ok.zip", "status": "completed"},
                        {"fs_id": "1002", "name": "fail.zip", "relative_path": "fail.zip", "status": "failed"},
                    ],
                }
            ],
            "download_batch_folder_name": "百度网盘_20260707_120000",
            "conflict_policy": "rename",
            "download_files": [
                {"selection_key": "baidu:all", "fs_id": "1001", "name": "ok.zip", "relative_path": "ok.zip", "status": "completed"},
                {"selection_key": "baidu:all", "fs_id": "1002", "name": "fail.zip", "relative_path": "fail.zip", "status": "failed", "failure_reason": "403"},
            ],
            "failed_files": [
                {"selection_key": "baidu:all", "fs_id": "1002", "name": "fail.zip", "relative_path": "fail.zip", "status": "failed", "failure_reason": "403"},
            ],
            "download_runtime": {"status": "failed"},
            "performance_metrics": {"failed_count": 1},
            "failure_reason": "403",
        },
        status=TaskStatus.FAILED,
        task_id="baidu-retry-trim-test",
    )

    await service.reset_task_for_retry(task)

    assert task.status == TaskStatus.PENDING
    assert task.current_step == "等待重新下载"
    assert task.task_metadata["retry_target_count"] == 1
    assert task.task_metadata["selected_keys"] == ["baidu:all"]
    assert task.task_metadata["conflict_policy"] == "resume"
    assert task.task_metadata["retry_original_conflict_policy"] == "rename"
    assert task.task_metadata["download_files"] == []
    assert task.task_metadata["failed_files"] == []
    assert task.task_metadata["download_runtime"] == {}
    assert task.task_metadata["performance_metrics"] == {}
    assert task.task_metadata["failure_reason"] == ""
    raw_files = task.task_metadata["raw_selected_items"][0]["share_files"]
    selected_files = task.task_metadata["selected_items"][0]["preview_files"]
    assert [item["name"] for item in raw_files] == ["fail.zip"]
    assert [item["name"] for item in selected_files] == ["fail.zip"]
    assert "bdstoken" in task.task_metadata["raw_selected_items"][0]
    assert "bdstoken" not in task.task_metadata["selected_items"][0]
    assert "share_files" not in task.task_metadata["selected_items"][0]


@pytest.mark.asyncio
async def test_baidu_download_file_concurrency_is_global(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.max_download_load = 1
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    entered = []
    release_first = asyncio.Event()

    async def fake_download_item(_task, _staging_dir, row, _download_files, _started, _cancel_event):
        entered.append(row["name"])
        if row["name"] == "one.zip":
            await release_first.wait()
        row["downloaded"] = row["size"]

    monkeypatch.setattr(service, "_download_share_item", fake_download_item)

    first_task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-global-limit-first",
    )
    second_task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-global-limit-second",
    )
    first_row = {"name": "one.zip", "relative_path": "one.zip", "status": "pending", "size": 10, "downloaded": 0}
    second_row = {"name": "two.zip", "relative_path": "two.zip", "status": "pending", "size": 10, "downloaded": 0}
    first_files = [first_row]
    second_files = [second_row]

    first = asyncio.create_task(service._download_share_item_guarded(
        first_task,
        str(tmp_path / "first"),
        first_row,
        0,
        first_files,
        time.monotonic(),
        asyncio.Event(),
        asyncio.Semaphore(1),
    ))
    while entered != ["one.zip"]:
        await asyncio.sleep(0)

    second = asyncio.create_task(service._download_share_item_guarded(
        second_task,
        str(tmp_path / "second"),
        second_row,
        0,
        second_files,
        time.monotonic(),
        asyncio.Event(),
        asyncio.Semaphore(1),
    ))
    await asyncio.sleep(0.05)

    assert entered == ["one.zip"]
    assert second_row["status"] == "pending"
    assert second_row["waiting_global_slot"] is True

    release_first.set()
    await asyncio.gather(first, second)

    assert entered == ["one.zip", "two.zip"]
    assert first_row["status"] == "completed"
    assert second_row["status"] == "completed"
    assert first_row["global_slot_limit"] == 1
    assert second_row["global_slot_limit"] == 1


def test_baidu_remote_temporary_transfer_dir_is_unique_per_row(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_20260605_153012_a1b2c3")

    first = service._remote_temporary_transfer_dir_for_row(None, {"fs_id": "fs-001", "_remote_transfer_scope": 0})
    second = service._remote_temporary_transfer_dir_for_row(None, {"fs_id": "fs-002", "_remote_transfer_scope": 1})

    assert first != second
    assert first.startswith("/km_20260605_153012_a1b2c3_")
    assert second.startswith("/km_20260605_153012_a1b2c3_")
    assert service._is_safe_remote_temporary_transfer_dir(first)
    assert service._is_safe_remote_temporary_transfer_dir(second)


@pytest.mark.asyncio
async def test_baidu_start_download_cancels_and_retries_remote_cleanup(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.storage.temp_path = str(tmp_path / "temp")
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_20260605_153012_a1b2c3")

    command_log = []

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
        abort_check=None,
        heartbeat_message="",
        max_runtime_seconds=0,
    ):
        command_log.append(tuple(args[1:]))
        command = args[1]
        if command == "download":
            task.cancel()
            raise asyncio.CancelledError()
        return

    transfer_calls = []

    async def fake_web_transfer(row, cookie, remote_tmp_dir_arg, *, share_url, pass_code=""):
        transfer_calls.append({
            "remote_tmp_dir": remote_tmp_dir_arg,
            "share_url": share_url,
            "pass_code": pass_code,
        })
        return {"errno": 0}

    monkeypatch.setattr(service, "preview_urls", fake_preview_urls)
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)
    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_web_transfer)

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={
            "urls": ["https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402"],
            "batch_name": "百度大文件测试",
            "conflict_policy": "resume",
        },
        status=TaskStatus.PROCESSING,
        task_id="baidu-cancel-test-task",
    )

    with pytest.raises(asyncio.CancelledError):
        await service.start_download_task(task)

    assert transfer_calls == [{
        "remote_tmp_dir": "/km_20260605_153012_a1b2c3",
        "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
        "pass_code": "0402",
    }]
    assert command_log.count(("cd", "/")) >= 2
    assert command_log.count(("rm", "/km_20260605_153012_a1b2c3")) >= 1
    assert task.task_metadata["download_runtime"]["status"] == "cancelled"
    assert task.task_metadata["output_finalize_status"] == "cancelled"
    assert task.task_metadata["staging_cleanup"]["success"] is True
    assert not (tmp_path / "temp" / "baidu_netdisk_downloads" / ".baidu-netdisk-staging" / "baidu-cancel-test-task").exists()


@pytest.mark.asyncio
async def test_baidu_remote_cleanup_rejects_unsafe_path(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    command_log = []

    async def fake_run_baidu_pcs_go_command(*args, **kwargs):
        command_log.append(args)

    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)

    task = Task(
        task_type=TaskType.BAIDU_NETDISK_DOWNLOAD,
        source_path="pan.baidu.com",
        metadata={"progress_log": []},
        status=TaskStatus.PROCESSING,
        task_id="baidu-unsafe-cleanup-test",
    )

    await service._cleanup_remote_temporary_transfer_dir(
        "C:/fake/BaiduPCS-Go.exe",
        "/",
        env={},
        log_path=str(tmp_path / "baidupcs-go.log"),
        task=task,
        retry_delayed=True,
    )

    assert command_log == []
    assert any("跳过异常百度网盘临时目录清理" in item["message"] for item in task.task_metadata["progress_log"])


@pytest.mark.asyncio
async def test_baidu_start_download_prefers_raw_selected_items_without_preview(monkeypatch, tmp_path):
    service = BaiduNetdiskService()
    config = DummyConfig()
    config.baidu_netdisk.download_root = str(tmp_path / "downloads")
    config.storage.temp_path = str(tmp_path / "temp")
    config.baidu_netdisk.max_download_load = 4
    expected_download_load = str(config.baidu_netdisk.max_download_load)
    monkeypatch.setattr("app.core.baidu_netdisk_service.get_config", lambda: config)

    command_log = []
    state = {}
    written_config = {}
    transfer_calls = []
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
        abort_check=None,
        heartbeat_message="",
        max_runtime_seconds=0,
    ):
        command_log.append({
            "args": tuple(args[1:]),
            "ignore_task_cancel": ignore_task_cancel,
            "max_runtime_seconds": max_runtime_seconds,
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
        if command in {"cd", "mkdir", "rm", "transfer"}:
            return
        raise AssertionError(f"unexpected command: {args}")

    original_write_config = service._write_baidu_pcsgo_cookie_config

    def capture_write_config(config_dir, cookie, *, workdir="/"):
        config_path = original_write_config(config_dir, cookie, workdir=workdir)
        written_config.update(json.loads(Path(config_path).read_text(encoding="utf-8")))
        return config_path

    async def fake_web_transfer(row, cookie, remote_tmp_dir, *, share_url, pass_code=""):
        transfer_calls.append({
            "fs_id": row.get("fs_id"),
            "cookie": cookie,
            "remote_tmp_dir": remote_tmp_dir,
            "share_url": share_url,
            "pass_code": pass_code,
        })
        return {"errno": 0}

    monkeypatch.setattr(service, "preview_urls", lambda *_args, **_kwargs: pytest.fail("raw_selected_items 已提供，不应重新预览"))
    monkeypatch.setattr(service, "_run_baidu_pcs_go_command", fake_run_baidu_pcs_go_command)
    monkeypatch.setattr(service, "_write_baidu_pcsgo_cookie_config", capture_write_config)
    monkeypatch.setattr(service, "_resolve_baidu_pcs_go_path", lambda: "C:/fake/BaiduPCS-Go.exe")
    monkeypatch.setattr(service, "_remote_temporary_transfer_dir", lambda _task: "/km_20260605_153012_a1b2c3")
    monkeypatch.setattr(service, "_transfer_share_item_by_web", fake_web_transfer)

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
    batch_folder = task.task_metadata["download_batch_folder_name"]
    assert re.fullmatch(r"百度网盘_\d{8}_\d{6}", batch_folder)
    assert (tmp_path / "downloads" / batch_folder / "狩龙人拉格纳121.mp4").read_bytes() == b"abcdef"
    assert [item["args"] for item in command_log][0] == ("config", "set", "-savedir", state["savedir"])
    config_user = written_config["baidu_user_list"][0]
    assert config_user["bduss"] == "test"
    assert config_user["stoken"] == "test"
    assert config_user["bdclnd"] == "rand-sk"
    assert config_user["cookies"] == "BDUSS=test; STOKEN=test; BDCLND=rand-sk"
    download_cmd = next(item["args"] for item in command_log if item["args"] and item["args"][0] == "download")
    assert download_cmd == (
        "download",
        "/km_20260605_153012_a1b2c3",
        "--saveto",
        state["savedir"],
        "--mode",
        "locate",
        "-p",
        "20",
        "-l",
        expected_download_load,
        "--retry",
        "5",
    )
    assert transfer_calls == [{
        "fs_id": "732325025154301",
        "cookie": "BDUSS=test; STOKEN=test; BDCLND=rand-sk",
        "remote_tmp_dir": "/km_20260605_153012_a1b2c3",
        "share_url": "https://pan.baidu.com/s/179-Q_PpccuyitQ2b_boyDw?pwd=0402",
        "pass_code": "0402",
    }]
    assert not any(item["args"][0] == "transfer" for item in command_log)
    assert task.task_metadata["download_files"][0]["status"] == "completed"
