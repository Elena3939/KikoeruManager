"""百度分享多层目录、分页和不完整响应回归。"""
import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.baidu_netdisk_service import BaiduNetdiskError, BaiduNetdiskService
from tests.test_baidu_netdisk_service import DummyConfig


def row(path, fs_id, is_dir=False):
    return {"path": path, "server_filename": path.rsplit("/", 1)[-1],
            "fs_id": fs_id, "isdir": int(is_dir), "size": 0 if is_dir else 10}


@pytest.mark.asyncio
@pytest.mark.parametrize("root", [True, False])
async def test_share_list_reads_all_pages(monkeypatch, root):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_config", lambda: DummyConfig().baidu_netdisk)
    pages = []

    async def fetch(url, *_args, **_kwargs):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        pages.append(page)
        start, end = (0, 100) if page == 1 else (100, 103)
        return {"errno": 0, "list": [row(f"/音轨/{i}.wav", i + 1) for i in range(start, end)]}

    monkeypatch.setattr(service, "_fetch_json", fetch)
    result = await service._fetch_share_list_payload({}, "", "", "1abcdefg", root=root)
    assert pages == [1, 2]
    assert len(result["list"]) == 103


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["repeated", "missing", "error", "early_end"])
async def test_share_list_rejects_incomplete_pages(monkeypatch, mode):
    service = BaiduNetdiskService()

    async def fetch(*_args, page=1, **_kwargs):
        if page == 1:
            return {"errno": 0, "list": [row("/1.wav", 1)], "has_more": 1}
        if mode == "repeated":
            return {"errno": 0, "list": [row("/1.wav", 1)]}
        if mode == "missing":
            return {"errno": 0}
        if mode == "error":
            return {"errno": -9, "errmsg": "读取失败"}
        return {"errno": 0, "list": [], "total": 2}

    monkeypatch.setattr(service, "_fetch_share_list_page_payload", fetch)
    if mode == "error":
        result = await service._fetch_share_list_payload({}, "", "", "1abcdefg")
        assert result["errno"] == -9
        assert "list" not in result
    else:
        with pytest.raises(BaiduNetdiskError):
            await service._fetch_share_list_payload({}, "", "", "1abcdefg")


@pytest.mark.asyncio
@pytest.mark.parametrize("multiple_roots", [False, True])
async def test_preview_recursively_expands_all_roots(monkeypatch, multiple_roots):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_config", lambda: DummyConfig().baidu_netdisk)
    async def tokens(*_args, **_kwargs):
        return {"shareid": "123", "share_uk": "456"}
    monkeypatch.setattr(service, "_fetch_share_page_tokens", tokens)
    tree = {
        "/": [row("/RJ01701262【完整版】", 1, True)],
        "/RJ01701262【完整版】": [row("/RJ01701262【完整版】/MP3", 2, True), row("/RJ01701262【完整版】/WAV", 3, True)],
        "/RJ01701262【完整版】/MP3": [row("/RJ01701262【完整版】/MP3/01.mp3", 4)],
        "/RJ01701262【完整版】/WAV": [row("/RJ01701262【完整版】/WAV/01.wav", 5)],
    }
    if multiple_roots:
        tree["/"].append(row("/特典", 6, True))
        tree["/特典"] = [row("/特典/bonus.wav", 7)]

    async def fetch(*_args, dir_path="/", **_kwargs):
        return {"errno": 0, "list": tree[dir_path]}
    monkeypatch.setattr(service, "_fetch_share_list_payload", fetch)
    detail = await service._fetch_share_detail({"share_id": "1abcdefg"})
    assert detail["file_count"] == (3 if multiple_roots else 2)
    assert detail["total_size"] == detail["file_count"] * 10
    assert all(not item["is_dir"] for item in detail["files"])
    assert detail["files"][0]["relative_path"] == ("特典/bonus.wav" if multiple_roots else "RJ01701262【完整版】/MP3/01.mp3")


@pytest.mark.asyncio
async def test_folder_failure_does_not_become_successful_preview(monkeypatch):
    service = BaiduNetdiskService()
    monkeypatch.setattr(service, "_config", lambda: DummyConfig().baidu_netdisk)
    async def tokens(*_args, **_kwargs):
        return {}
    async def fetch(*_args, root=True, **_kwargs):
        if root:
            return {"errno": 0, "list": [row("/作品", 1, True)]}
        return {"errno": -9, "errmsg": "目录读取失败"}
    monkeypatch.setattr(service, "_fetch_share_page_tokens", tokens)
    monkeypatch.setattr(service, "_fetch_share_list_payload", fetch)
    result = await service.preview_urls(["https://pan.baidu.com/s/1abcdefg"])
    assert result["success"] is False
    assert result["items"][0]["preview_files"] == []
    assert "目录读取失败" in result["items"][0]["reason"]


@pytest.mark.asyncio
async def test_recursive_preview_cancels_directory_requests(monkeypatch):
    service = BaiduNetdiskService()
    started = asyncio.Event()
    active = set()

    async def fetch(*_args, dir_path, **_kwargs):
        active.add(dir_path)
        if len(active) == 2:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active.remove(dir_path)

    monkeypatch.setattr(service, "_fetch_share_list_payload", fetch)
    folders = service._normalize_share_file_list([row("/MP3", 1, True), row("/WAV", 2, True)])
    task = asyncio.create_task(service._expand_share_file_list({}, "", "", "", folders))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == set()
