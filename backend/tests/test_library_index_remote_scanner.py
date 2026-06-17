from __future__ import annotations

import pytest

from app.core.library_index.remote_scanner import RemoteScanner


class EmptySearchListClient:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.list_calls: list[tuple[str, int]] = []

    async def start_search(self, folder_path: str, keyword: str, recursive: bool = True):
        self.started = True
        assert folder_path == "/AMSR"
        assert keyword == "*"
        assert recursive is True
        return {"taskid": "search-1"}

    async def list_search(
        self,
        taskid: str,
        offset: int = 0,
        limit: int = 200,
        sort_by: str = "name",
        sort_direction: str = "asc",
    ):
        return {"finished": True, "files": []}

    async def stop_search(self, taskid: str):
        self.stopped = True

    async def list(
        self,
        folder_path: str,
        offset: int = 0,
        limit: int = 200,
        sort_by: str = "name",
        sort_direction: str = "asc",
    ):
        self.list_calls.append((folder_path, offset))
        if folder_path == "/AMSR" and offset == 0:
            return {
                "total": 1,
                "files": [
                    {
                        "name": "社团A",
                        "path": "/AMSR/社团A",
                        "isdir": True,
                        "additional": {"time": {"mtime": 100}, "size": 0},
                    }
                ],
            }
        if folder_path == "/AMSR/社团A" and offset == 0:
            return {
                "total": 1,
                "files": [
                    {
                        "name": "RJ01000001.wav",
                        "path": "/AMSR/社团A/RJ01000001.wav",
                        "isdir": False,
                        "additional": {"time": {"mtime": 101}, "size": 1234},
                    }
                ],
            }
        return {"total": 0, "files": []}

    async def list_share(self, *args, **kwargs):
        raise AssertionError("本用例不应该扫描 share 根目录")


@pytest.mark.asyncio
async def test_remote_scanner_falls_back_to_list_walk_when_search_returns_empty():
    client = EmptySearchListClient()
    scanner = RemoteScanner(page_size=100, wait_initial_delay=0.01)

    entries = [
        entry
        async for entry in scanner.scan("remote-library-2", client, "/AMSR")
    ]

    assert client.started is True
    assert client.stopped is True
    assert [(entry.relative_path, entry.entry_type, entry.size) for entry in entries] == [
        ("社团A", "dir", 0),
        ("社团A/RJ01000001.wav", "file", 1234),
    ]
    assert entries[1].rjcode == "RJ01000001"
    assert ("/AMSR", 0) in client.list_calls
    assert ("/AMSR/社团A", 0) in client.list_calls
