import builtins
import errno
import os
from types import SimpleNamespace

import pytest

from app.core import staged_file_move as fs
from app.core import filter_recovery_service as recovery_module
from app.core import file_move_diagnostics as diagnostics
from app.config.settings import FileMoveConfig
from app.core.filter_recovery_service import FilterRecoveryService


@pytest.fixture
def move_setup(monkeypatch, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    config = SimpleNamespace(
        host_enabled=True, filter_verify_hashes=False,
        socket_path="unused", request_timeout_seconds=1,
        journal_path=str(tmp_path / "journal"),
    )
    monkeypatch.setattr(fs, "move_config", lambda: config)
    monkeypatch.setattr(recovery_module, "get_config", lambda: SimpleNamespace(file_move=config))
    publish = fs.publish_path

    def cross_mount(left, right, **kwargs):
        if os.fspath(left) == str(source):
            raise OSError(errno.EXDEV, "测试跨挂载")
        return publish(left, right, **kwargs)

    monkeypatch.setattr(fs, "publish_path", cross_mount)
    return source, target, config


def install_clone(monkeypatch, *, after_clone=None):
    original_open = builtins.open
    cloned = []

    class Client:
        def __init__(self, *_):
            pass

        def probe(self, *_):
            return {"same_filesystem": True, "mapping_version": "test"}

        def clone(self, source, destination, version, checkpoint, register, on_created=None):
            checkpoint()
            # 测试环境用独立副本模拟宿主已成功完成的克隆。
            with original_open(source, "rb") as incoming, original_open(destination, "xb") as outgoing:
                outgoing.write(incoming.read())
            if on_created:
                on_created(fs.identity(destination))
            cloned.append(source)
            if after_clone:
                after_clone(source, destination)

    monkeypatch.setattr(fs, "HostMoveClient", Client)
    return cloned


@pytest.mark.parametrize("directory", [False, True])
def test_verified_clone_does_not_reread_payload(move_setup, monkeypatch, directory):
    source, target, _ = move_setup
    if directory:
        source.mkdir()
        (source / "audio.wav").write_bytes(b"audio" * 100)
        os.link(source / "audio.wav", source / "linked.wav")
    else:
        source.write_bytes(b"audio" * 100)
    cloned = install_clone(monkeypatch)
    original_open = builtins.open

    def reject_payload_read(path, mode="r", *args, **kwargs):
        if mode == "rb":
            pytest.fail("成功克隆后不得全量重读内容")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_payload_read)
    fs.move_path_sync(source, target)
    assert not source.exists()
    assert len(cloned) == 1
    payload = target / "audio.wav" if directory else target
    with original_open(payload, "rb") as incoming:
        assert incoming.read() == b"audio" * 100
    if directory:
        assert os.stat(target / "audio.wav").st_ino == os.stat(target / "linked.wav").st_ino


def test_clone_still_rejects_source_changes(move_setup, monkeypatch):
    source, target, _ = move_setup
    source.write_bytes(b"original")

    def mutate(src, _dst):
        with open(src, "ab") as stream:
            stream.write(b"changed")

    install_clone(monkeypatch, after_clone=mutate)
    with pytest.raises(RuntimeError, match="来源发生变化"):
        fs.move_path_sync(source, target)
    assert source.exists() and not target.exists()


def test_clone_still_rejects_wrong_target_size(move_setup, monkeypatch):
    source, target, _ = move_setup
    source.write_bytes(b"original")

    def truncate(_src, dst):
        with open(dst, "wb") as stream:
            stream.write(b"x")

    install_clone(monkeypatch, after_clone=truncate)
    with pytest.raises(RuntimeError, match="搬运副本校验失败"):
        fs.move_path_sync(source, target)
    assert source.read_bytes() == b"original" and not target.exists()


@pytest.mark.parametrize("clone", [False, True])
@pytest.mark.parametrize("verify_hashes", [False, True])
@pytest.mark.parametrize("directory", [False, True])
def test_filter_hash_switch_applies_to_capture_migration_and_restore(
    move_setup, monkeypatch, tmp_path, clone, verify_hashes, directory,
):
    source, target, config = move_setup
    config.host_enabled = clone
    config.filter_verify_hashes = verify_hashes
    if clone:
        install_clone(monkeypatch)
    content = b"filtered audio"
    if directory:
        source.mkdir()
        (source / "audio.wav").write_bytes(content)
    else:
        source.write_bytes(content)
    original_open = builtins.open
    reads = []

    def track_reads(path, mode="r", *args, **kwargs):
        if mode == "rb":
            reads.append(os.fspath(path))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", track_reads)
    publish = fs.publish_path

    def cross_mount(left, right, **kwargs):
        if not os.path.basename(left).startswith(".kikoerumanager-move-"):
            raise OSError(errno.EXDEV, "测试全部搬运跨挂载")
        return publish(left, right, **kwargs)

    monkeypatch.setattr(fs, "publish_path", cross_mount)
    service = FilterRecoveryService(str(tmp_path / "recovery"))

    def check_reads():
        # 流式复制只读来源一次；克隆模拟器使用原始 open，不计入应用层读取。
        assert len(reads) == (0 if clone else 1) + (2 if verify_hashes else 0)
        reads.clear()

    item = service.capture_item(
        "hash-switch", str(source), relative_path="removed",
        entry_type="dir" if directory else "file", size=len(content),
    )
    check_reads()
    assert not source.exists()
    service.prepare_archive_storage(
        "hash-switch", rjcode="RJ123456", processed_root=tmp_path / "archive",
    )
    check_reads()
    service.finalize_task("hash-switch", final_root=str(target))
    manifest = service._read_manifest("hash-switch")
    payload = service._payload_path("hash-switch", item)
    restored = service._restore_local(payload, manifest["target"], manifest["items"][0])
    check_reads()
    assert restored == str(target / "removed")
    restored_file = target / "removed" / "audio.wav" if directory else target / "removed"
    assert restored_file.read_bytes() == content
    assert not payload.exists()


@pytest.mark.parametrize("clone", [False, True])
def test_filter_enabled_hash_check_rejects_same_size_corruption(
    move_setup, monkeypatch, tmp_path, clone,
):
    source, _target, config = move_setup
    source.write_bytes(b"original")
    config.host_enabled = clone
    config.filter_verify_hashes = True
    if clone:
        install_clone(monkeypatch)
    phase = fs._phase

    def corrupt(name, src, dst, callback=None):
        if name == "校验":
            with open(dst, "wb") as stream:
                stream.write(b"corrupt!")
        phase(name, src, dst, callback)

    monkeypatch.setattr(fs, "_phase", corrupt)
    service = FilterRecoveryService(str(tmp_path / "recovery"))
    with pytest.raises(RuntimeError, match="SHA-256 校验失败"):
        service.capture_item(
            "corrupt-filter", str(source), relative_path="audio.wav", entry_type="file", size=8,
        )
    assert source.read_bytes() == b"original"
    manifest = service._read_manifest("corrupt-filter")
    assert not any(item["recovery_status"] == "available" for item in manifest["items"])


def test_hash_switch_defaults_off_and_survives_config_roundtrip():
    assert FileMoveConfig().filter_verify_hashes is False
    config = FileMoveConfig(filter_verify_hashes=True)
    assert FileMoveConfig.model_validate(config.model_dump()).filter_verify_hashes is True


def test_hash_switch_change_does_not_require_host_connection(monkeypatch):
    current = SimpleNamespace(file_move=FileMoveConfig(host_enabled=True))
    candidate = SimpleNamespace(
        file_move=FileMoveConfig(host_enabled=True, filter_verify_hashes=True),
    )
    monkeypatch.setattr(diagnostics, "business_roots", lambda _: ["/audio"])
    monkeypatch.setattr(
        diagnostics, "runtime_status", lambda _: pytest.fail("哈希开关不改变宿主连接"),
    )
    diagnostics.validate_configuration_update(current, candidate)


def test_filtered_clone_remains_restorable(move_setup, monkeypatch, tmp_path):
    source, target, _ = move_setup
    source.write_bytes(b"filtered audio")
    cloned = install_clone(monkeypatch)
    service = FilterRecoveryService(str(tmp_path / "recovery"))
    task_id = "clone-filter-task"
    service.begin_capture(task_id)
    item = service.capture_item(
        task_id, str(source), relative_path="audio.wav", entry_type="file", size=14,
    )
    assert item["recovery_status"] == "available"
    assert not source.exists() and len(cloned) == 1
    finalized = service.finalize_task(task_id, final_root=str(target))
    assert finalized[0]["restore_relative_path"] == "audio.wav"
    manifest = service._read_manifest(task_id)
    payload = service._payload_path(task_id, item)

    # 复原也模拟跨挂载，确保同一克隆校验路径仍能保留可恢复内容。
    publish = fs.publish_path

    def cross_mount(left, right, **kwargs):
        if os.fspath(left) == str(payload):
            raise OSError(errno.EXDEV, "测试复原跨挂载")
        return publish(left, right, **kwargs)

    monkeypatch.setattr(fs, "publish_path", cross_mount)
    restored = service._restore_local(payload, manifest["target"], finalized[0])
    assert restored == str(target / "audio.wav")
    assert (target / "audio.wav").read_bytes() == b"filtered audio"
    assert not payload.exists() and len(cloned) == 2


@pytest.mark.parametrize("host_enabled", [False, True])
def test_stream_still_hashes_and_rejects_same_size_corruption(
    move_setup, monkeypatch, host_enabled,
):
    source, target, config = move_setup
    config.host_enabled = host_enabled
    source.write_bytes(b"original")

    class DifferentFilesystem:
        def __init__(self, *_):
            pass

        def probe(self, *_):
            return {"same_filesystem": False, "mapping_version": "test"}

        def clone(self, *_args, **_kwargs):
            pytest.fail("跨文件系统不得克隆")

    monkeypatch.setattr(fs, "HostMoveClient", DifferentFilesystem)

    def corrupt(phase):
        if phase == "校验":
            stage = next(target.parent.glob(".kikoerumanager-move-*.part"))
            stage.write_bytes(b"corrupt!")

    with pytest.raises(RuntimeError, match="SHA-256 校验失败"):
        fs.move_path_sync(source, target, verify_hashes=True, phase_cb=corrupt)
    assert source.read_bytes() == b"original" and not target.exists()
