"""多来源协议的路径、身份与常数级持久化验证；ioctl 用可控替身。"""
import contextlib
import importlib
import os
import socketserver
import sys
import uuid
from types import SimpleNamespace

import pytest

from app.core.file_move_protocol import identity


@pytest.fixture
def multi_host(tmp_path, monkeypatch):
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace())
        monkeypatch.setattr(socketserver, "ThreadingUnixStreamServer", socketserver.ThreadingTCPServer, raising=False)
    host = importlib.import_module("app.core.host_file_mover")
    roots = {name: tmp_path / name for name in ("new", "old", "stage")}
    for root in roots.values():
        root.mkdir()
    executor = host.Executor({"mappings": [], "records": str(tmp_path / "records"),
                              "allowed_uid": 0, "allowed_gid": 0})
    descriptors = {}
    real_open = os.open
    @contextlib.contextmanager
    def open_path(value, parent=False):
        parts = value.strip("/").split("/")
        path = roots[parts[0]].joinpath(*parts[1:])
        descriptor = real_open(str(path.parent if parent else path), os.O_RDONLY) if not (os.name == "nt" and (path.parent if parent else path).is_dir()) else None
        if descriptor is None:
            descriptor = 100000 + len(descriptors)
        descriptors[descriptor] = path.parent if parent else path
        try:
            yield descriptor, path.name
        finally:
            if descriptor < 100000:
                os.close(descriptor)
    real_fstat, real_listdir = os.fstat, os.listdir
    def fstat(fd):
        # Windows 的句柄与路径 ctime 语义不同；宿主协议运行在 Linux。
        return os.stat(descriptors[fd]) if fd in descriptors else real_fstat(fd)
    def opening(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None:
            target = descriptors[dir_fd] / path
            descriptor = real_open(str(target), flags, mode)
            descriptors[descriptor] = target
            return descriptor
        return real_open(path, flags, mode)
    def ioctl(target, command, source):
        while chunk := os.read(source, 4096):
            os.write(target, chunk)
    monkeypatch.setattr(executor, "open_path", open_path)
    monkeypatch.setattr(host, "filesystem_id", lambda fd: "test-filesystem")
    monkeypatch.setattr(os, "open", opening)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "listdir", lambda value: real_listdir(descriptors[value]) if isinstance(value, int) and value in descriptors else real_listdir(value))
    monkeypatch.setattr(host.fcntl, "ioctl", ioctl, raising=False)
    monkeypatch.setattr(os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), raising=False)
    monkeypatch.setattr(os, "fchown", lambda *args: None, raising=False)
    monkeypatch.setattr(os, "fchmod", lambda *args: None, raising=False)
    operation = str(uuid.uuid4())
    begin = {"action": "begin_multi_directory", "operation_id": operation,
             "roots": {"new": "/new", "old": "/old"}, "destination": "/stage",
             "root_identities": {key: identity(roots[key]) for key in ("new", "old")},
             "destination_identity": identity(roots["stage"]), "mapping_version": executor.mapping_version}
    return executor, roots, begin


def member(begin, root, path, expected):
    return {"action": "prepare_multi_member", "operation_id": begin["operation_id"],
            "root_id": root, "source_relative": path, "target_relative": path, "source_identity": expected}


def test_multiple_roots_and_constant_transaction_writes(multi_host, monkeypatch):
    executor, roots, begin = multi_host
    for key in ("new", "old"):
        for index in range(12):
            (roots[key] / f"{key}-{index}").write_bytes(key.encode())
    begin["root_identities"] = {key: identity(roots[key]) for key in ("new", "old")}
    writes = []
    save = executor._save
    monkeypatch.setattr(executor, "_save", lambda record: (writes.append(record["state"]), save(record))[-1])
    executor.multi_directory_transaction(begin)
    for key in ("new", "old"):
        for index in range(12):
            path = f"{key}-{index}"
            executor.multi_directory_transaction(member(begin, key, path, identity(roots[key] / path)))
            assert (roots["stage"] / path).read_bytes() == key.encode()
    assert writes == ["preparing"]
    executor.multi_directory_transaction({"action": "finish_multi_directory", "operation_id": begin["operation_id"]})
    executor.control({"action": "release", "operation_id": begin["operation_id"]})
    assert writes == ["preparing", "ready", "released"]


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../../b", "a\\b", "a/./b"])
def test_rejects_escape(multi_host, path):
    executor, roots, begin = multi_host
    executor.multi_directory_transaction(begin)
    with pytest.raises(PermissionError):
        executor.multi_directory_transaction(member(begin, "new", path, {}))


def test_member_identity_and_duplicate_destination_rejected(multi_host):
    executor, roots, begin = multi_host
    (roots["new"] / "a").write_bytes(b"a")
    begin["root_identities"]["new"] = identity(roots["new"])
    executor.multi_directory_transaction(begin)
    request = member(begin, "new", "a", identity(roots["new"] / "a"))
    invalid = {**request, "source_identity": {}}
    with pytest.raises(RuntimeError, match="来源已变化"):
        executor.multi_directory_transaction(invalid)
    executor.multi_directory_transaction(request)
    with pytest.raises(FileExistsError):
        executor.multi_directory_transaction(request)


def test_begin_rejects_stale_root_and_mapping(multi_host):
    executor, roots, begin = multi_host
    with pytest.raises(RuntimeError, match="映射"):
        executor.multi_directory_transaction({**begin, "mapping_version": "stale"})
    with pytest.raises(RuntimeError, match="来源根"):
        executor.multi_directory_transaction({**begin, "root_identities": {}})


def test_cancelled_multi_operation_rejects_late_member(multi_host):
    executor, roots, begin = multi_host
    executor.multi_directory_transaction(begin)
    executor.control({"action": "cancel", "operation_id": begin["operation_id"]})
    with pytest.raises(RuntimeError, match="已终止"):
        executor.multi_directory_transaction(member(begin, "new", "a", {}))
