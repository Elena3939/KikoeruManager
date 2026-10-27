"""扁平化慢盘与取消回归：事件循环可运行，目录事务完整结束。"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.core import rename_service


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_flatten_slow_move_keeps_loop_alive_and_directory_intact(monkeypatch, tmp_path, cancel):
    root = tmp_path / "work"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "audio.wav").write_bytes(b"audio")
    monkeypatch.setattr(rename_service, "get_config", lambda: SimpleNamespace(
        rename=SimpleNamespace(flatten_depth=1),
    ))
    entered, proceed = threading.Event(), threading.Event()
    original = rename_service.move_path_sync
    loop_thread = threading.get_ident()
    calls = []

    def slow_move(source, target):
        assert threading.get_ident() != loop_thread
        original(source, target)
        calls.append((source, target))
        if len(calls) == 1:
            entered.set()
            assert proceed.wait(5)

    monkeypatch.setattr(rename_service, "move_path_sync", slow_move)
    transforms = []
    task = asyncio.create_task(rename_service.RenameService().flatten_single_subfolder(str(root), transforms))
    try:
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            # 重复取消也必须等待目录事务完成。
            task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        assert transforms == []
    finally:
        proceed.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task == str(root)
    assert (root / "audio.wav").read_bytes() == b"audio"
    assert list(tmp_path.iterdir()) == [root]
    assert transforms == [{"parent_relative_path": "", "removed_segment": "nested"}]


@pytest.mark.asyncio
async def test_empty_directory_cleanup_runs_in_worker_and_preserves_root(monkeypatch, tmp_path):
    root = tmp_path / "root"
    (root / "empty" / "nested").mkdir(parents=True)
    (root / "file").write_bytes(b"keep")
    service = rename_service.RenameService()
    original = service.remove_empty_folders
    loop_thread = threading.get_ident()

    def checked(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "remove_empty_folders", checked)
    await service.remove_empty_folders_async(str(root))
    assert (root / "file").read_bytes() == b"keep"
    assert not (root / "empty").exists()
    (root / "file").unlink()
    await service.remove_empty_folders_async(str(root))
    assert root.is_dir()
