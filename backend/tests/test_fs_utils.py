import asyncio
import errno
import time

import pytest

from app.core import fs_utils


@pytest.mark.asyncio
async def test_cross_device_move_does_not_block_event_loop(monkeypatch, tmp_path):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"x" * (128 * 1024))

    def reject_rename(_src, _dst):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(fs_utils.os, "rename", reject_rename)
    loop_tick = asyncio.Event()

    async def mark_loop_tick():
        await asyncio.sleep(0.01)
        loop_tick.set()

    tick_task = asyncio.create_task(mark_loop_tick())
    move_task = asyncio.create_task(
        fs_utils.move_path_efficient(
            str(source),
            str(target),
            buffer_size=1024,
            progress_throttle_bytes=1024,
            progress_cb=lambda _copied, _total: time.sleep(0.001),
        )
    )

    await asyncio.wait_for(loop_tick.wait(), timeout=0.1)
    assert move_task.done() is False
    await move_task
    await tick_task

    assert source.exists() is False
    assert target.stat().st_size == 128 * 1024


@pytest.mark.asyncio
async def test_cross_device_move_cancellation_preserves_source(monkeypatch, tmp_path):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"x" * (64 * 1024))

    def reject_rename(_src, _dst):
        raise OSError(errno.EXDEV, "cross-device link")

    checks = {"count": 0}

    def should_cancel():
        checks["count"] += 1
        return checks["count"] >= 4

    monkeypatch.setattr(fs_utils.os, "rename", reject_rename)

    with pytest.raises(asyncio.CancelledError):
        await fs_utils.move_path_efficient(
            str(source),
            str(target),
            buffer_size=1024,
            cancel_check=should_cancel,
        )

    assert source.exists() is True
    assert target.exists() is True
    assert target.stat().st_size < source.stat().st_size
