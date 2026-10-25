import asyncio
import errno
import json
import os
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from app.core import staged_file_move as fs
from app.core.file_move_recovery import restart_preparing
from app.core.host_file_move_client import HostMoveError


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    config = SimpleNamespace(host_enabled=False, socket_path="unused", request_timeout_seconds=1,
                             journal_path=str(tmp_path / "journal"))
    monkeypatch.setattr(fs, "move_config", lambda: config)
    return config


def cross_device(monkeypatch, source):
    original = fs.publish_path

    def publish(left, right, **kwargs):
        if os.fspath(left) == str(source):
            raise OSError(errno.EXDEV, "测试跨挂载")
        return original(left, right, **kwargs)

    monkeypatch.setattr(fs, "publish_path", publish)


@pytest.mark.parametrize("replace", [False, True])
def test_move_rejects_source_ancestor_and_descendant(tmp_path, replace):
    source = tmp_path / "parent" / "source"
    source.mkdir(parents=True)
    (source / "file").write_bytes(b"keep")
    operation = fs.move_path_replacing_sync if replace else fs.move_path_sync
    for target in (source.parent, source / "nested"):
        with pytest.raises(ValueError, match="祖先"):
            operation(source, target)
    assert (source / "file").read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_generic_async_cancel_waits_and_propagates_checkpoint(tmp_path):
    entered, proceed, stopped = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        proceed.wait(2)
        try:
            fs._check_scope()
            pytest.fail("取消后不得继续发布")
        finally:
            stopped.set()

    task = asyncio.create_task(fs.run_file_operation_async(operation))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


def test_native_rename_never_contacts_host(settings, monkeypatch, tmp_path):
    settings.host_enabled = True
    monkeypatch.setattr(fs, "HostMoveClient", lambda *_: pytest.fail("不应连接执行器"))
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"hello")
    fs.move_path_sync(source, target)
    assert target.read_bytes() == b"hello" and not source.exists()


@pytest.mark.parametrize("code", [errno.EACCES, errno.EEXIST, errno.ENOENT, errno.ENOSPC])
def test_only_exdev_can_copy(monkeypatch, tmp_path, code):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("a")
    monkeypatch.setattr(fs, "publish_path", lambda *_a, **_k: (_ for _ in ()).throw(OSError(code, "拒绝")))
    monkeypatch.setattr(fs, "copy_path_exclusive_sync", lambda *_a, **_k: pytest.fail("不应复制"))
    with pytest.raises(OSError) as error:
        fs.move_path_sync(source, target)
    assert error.value.errno == code and source.exists()


def test_stream_tree_preserves_hardlinks(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.mkdir()
    (source / "one").write_bytes(b"x" * 100)
    os.link(source / "one", source / "two")
    cross_device(monkeypatch, source)
    fs.move_path_sync(source, target, verify_hashes=True)
    assert not source.exists()
    assert os.stat(target / "one").st_ino == os.stat(target / "two").st_ino


@pytest.mark.parametrize("same", [True, False])
def test_host_selects_clone_or_stream(settings, monkeypatch, tmp_path, same):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"content")
    calls = []
    settings.host_enabled = True

    class Client:
        def __init__(self, *_):
            pass

        def probe(self, *_):
            return {"same_filesystem": same, "mapping_version": "v"}

        def clone(self, src, dst, version, checkpoint, register, on_created=None):
            calls.append(version)
            checkpoint()
            with open(dst, "xb") as output:
                output.write(open(src, "rb").read())

    monkeypatch.setattr(fs, "HostMoveClient", Client)
    cross_device(monkeypatch, source)
    fs.move_path_sync(source, target)
    assert calls == (["v"] if same else [])
    assert target.read_bytes() == b"content"


def test_host_offline_preserves_source(settings, monkeypatch, tmp_path):
    settings.host_enabled = True
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"keep")
    cross_device(monkeypatch, source)
    with pytest.raises(HostMoveError):
        fs.move_path_sync(source, target)
    assert source.read_bytes() == b"keep" and not target.exists()


def test_publish_race_preserves_both(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"original")
    cross_device(monkeypatch, source)
    original = fs.copy_path_exclusive_sync

    def race(*args, **kwargs):
        result = original(*args, **kwargs)
        target.write_bytes(b"competitor")
        return result

    monkeypatch.setattr(fs, "copy_path_exclusive_sync", race)
    with pytest.raises(FileExistsError):
        fs.move_path_sync(source, target)
    assert source.read_bytes() == b"original" and target.read_bytes() == b"competitor"


def test_resume_cleanup_never_republishes(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"original")
    cross_device(monkeypatch, source)
    clean = fs._clean_source
    monkeypatch.setattr(fs, "_clean_source", lambda *_: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(fs.MoveCleanupPending):
        fs.move_path_sync(source, target)
    inode = target.stat().st_ino
    monkeypatch.setattr(fs, "_clean_source", clean)
    monkeypatch.setattr(fs, "publish_path", lambda *_a, **_k: pytest.fail("禁止再次发布"))
    fs.move_path_sync(source, target)
    assert not source.exists() and target.stat().st_ino == inode


def test_changed_source_blocks_entire_cleanup(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.mkdir()
    (source / "one").write_text("one")
    cross_device(monkeypatch, source)
    clean = fs._clean_source
    monkeypatch.setattr(fs, "_clean_source", lambda *_: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(fs.MoveCleanupPending):
        fs.move_path_sync(source, target)
    (source / "new").write_text("new")
    monkeypatch.setattr(fs, "_clean_source", clean)
    with pytest.raises(fs.MoveCleanupPending):
        fs.move_path_sync(source, target)
    assert (source / "one").exists() and (source / "new").exists()


def test_preparing_recovery_quarantines_owned_stage(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"x" * 10000)
    cross_device(monkeypatch, source)
    count = 0

    def cancelled():
        nonlocal count
        count += 1
        return count > 4

    with pytest.raises(asyncio.CancelledError):
        fs.move_path_sync(source, target, cancel_check=cancelled, buffer_size=128)
    assert source.exists() and not target.exists()
    quarantined = restart_preparing(source)
    assert quarantined and os.path.exists(quarantined)
    fs.move_path_sync(source, target)
    assert target.stat().st_size == 10000


def test_symlink_is_copied_as_link(monkeypatch, tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.mkdir()
    try:
        os.symlink("missing", source / "link")
    except OSError:
        pytest.skip("当前 Windows 用户无创建符号链接权限")
    cross_device(monkeypatch, source)
    fs.move_path_sync(source, target)
    assert os.readlink(target / "link") == "missing"


def test_destination_alias_inside_source_rejected(tmp_path):
    source = tmp_path / "a"
    source.mkdir()
    with pytest.raises(ValueError):
        fs.move_path_sync(source, source / "nested")


@pytest.mark.asyncio
async def test_async_cancel_waits_for_worker(monkeypatch, tmp_path):
    entered, exited = threading.Event(), threading.Event()

    def slow(*_args, **_kwargs):
        entered.set()
        try:
            while True:
                fs._check_scope()
                time.sleep(0.001)
        finally:
            time.sleep(0.03)
            exited.set()

    monkeypatch.setattr(fs, "move_path_sync", slow)
    task = asyncio.create_task(fs.move_path_async("a", "b"))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set()


@pytest.mark.parametrize("state", ["staged", "backed_up", "published", "cleaning"])
def test_replacement_recovers_every_commit_window(monkeypatch, tmp_path, state):
    source, target = tmp_path / "new", tmp_path / "old"
    source.mkdir()
    target.mkdir()
    (source / "new.txt").write_text("new")
    (target / "old.txt").write_text("old")
    save = fs.atomic_json
    injected = False

    def crash(path, record):
        nonlocal injected
        if record["state"] == state and not injected:
            injected = True
            raise SystemExit("模拟进程退出")
        save(path, record)

    monkeypatch.setattr(fs, "atomic_json", crash)
    with pytest.raises((SystemExit, fs.MoveCleanupPending)):
        fs.move_path_replacing_sync(source, target)
    monkeypatch.setattr(fs, "atomic_json", save)
    fs.move_path_replacing_sync(source, target)
    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()
    assert not source.exists()
    assert not list(tmp_path.glob("old.kikoerumanager-*"))


def test_cross_device_replacement_keeps_old_target_while_copying(monkeypatch, tmp_path):
    source, target = tmp_path / "new", tmp_path / "old"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    cross_device(monkeypatch, source)
    copy = fs.copy_path_exclusive_sync

    def checking(*args, **kwargs):
        assert target.read_bytes() == b"old"
        return copy(*args, **kwargs)

    monkeypatch.setattr(fs, "copy_path_exclusive_sync", checking)
    fs.move_path_replacing_sync(source, target)
    assert target.read_bytes() == b"new" and not source.exists()


def test_replacement_publish_failure_restores_backup(monkeypatch, tmp_path):
    source, target = tmp_path / "new", tmp_path / "old"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    publish = fs.publish_path

    def fail(left, right, **kwargs):
        if str(left).endswith(".part") and str(right) == str(target):
            raise PermissionError("目标暂时不可写")
        return publish(left, right, **kwargs)

    monkeypatch.setattr(fs, "publish_path", fail)
    with pytest.raises(PermissionError):
        fs.move_path_replacing_sync(source, target)
    assert target.read_bytes() == b"old"
    monkeypatch.setattr(fs, "publish_path", publish)
    fs.move_path_replacing_sync(source, target)
    assert target.read_bytes() == b"new"


def test_clone_failure_does_not_fall_back_to_copy(settings, monkeypatch, tmp_path):
    settings.host_enabled = True
    source, target = tmp_path / "new", tmp_path / "target"
    source.write_bytes(b"new")
    cross_device(monkeypatch, source)

    class Client:
        def __init__(self, *_):
            pass

        def probe(self, *_):
            return {"same_filesystem": True, "mapping_version": "v"}

        def clone(self, *_, **_kwargs):
            raise HostMoveError("映射已变化或克隆空间不足")

    monkeypatch.setattr(fs, "HostMoveClient", Client)
    with pytest.raises(HostMoveError):
        fs.move_path_sync(source, target)
    assert source.read_bytes() == b"new" and not target.exists()


def test_cleanup_cancel_stops_between_members_and_resumes(monkeypatch, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    for name in ("one", "two", "three"):
        (source / name).write_text(name)
    cross_device(monkeypatch, source)
    deleted = []
    unlink = fs.os.unlink

    def remove(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if os.path.dirname(os.fspath(path)) == str(source):
            deleted.append(path)
        return result

    monkeypatch.setattr(fs.os, "unlink", remove)
    with pytest.raises(asyncio.CancelledError):
        fs.move_path_sync(source, target, cancel_check=lambda: bool(deleted))
    assert len(deleted) == 1
    assert len(list(source.iterdir())) == 2
    assert len(list(target.iterdir())) == 3
    fs.move_path_sync(source, target)
    assert not source.exists() and len(list(target.iterdir())) == 3
