"""同步文件搬运核心：独占暂存、无覆盖发布及可恢复的来源清理。"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import ctypes
import errno
import hashlib
import json
import logging
import os
import shutil
import stat
import threading
import uuid
from pathlib import Path

from .file_move_protocol import atomic_json, fsync_directory, identity
from .host_file_move_client import HostMoveClient, HostMoveError

logger = logging.getLogger(__name__)
BUFFER_SIZE = 8 * 1024 * 1024
_cancel_scope = contextvars.ContextVar("file_move_cancel", default=None)


def _check_scope():
    event = _cancel_scope.get()
    if event is not None and event.is_set():
        raise asyncio.CancelledError()


async def run_file_operation_async(operation, *args, **kwargs):
    """把取消传入同步文件事务，并等待线程退出后才交还业务调用方。"""
    stopped = threading.Event()
    token = _cancel_scope.set(stopped)
    try:
        worker = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    finally:
        _cancel_scope.reset(token)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        stopped.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                pass
            except Exception:
                break
        with contextlib.suppress(BaseException):
            worker.result()
        raise


class MoveCleanupPending(RuntimeError):
    """目标已发布，必须恢复清源，业务层不得回滚或再次覆盖目标。"""


def copy_file_publish_sync(source, destination, *, overwrite=False, checkpoint=None):
    """保留来源的单文件提交；旧目标直到完整暂存就绪才被替换。"""
    if not stat.S_ISREG(os.lstat(source).st_mode):
        raise ValueError("单文件提交仅支持普通文件")
    destination = os.path.abspath(destination)
    stage = os.path.join(os.path.dirname(destination),
                         ".kikoerumanager-copy-" + uuid.uuid4().hex + ".part")
    created = []
    try:
        copy_path_exclusive_sync(source, stage, checkpoint=checkpoint, on_created=created.append)
        _check_scope()
        if checkpoint:
            checkpoint()
        publish_path(stage, destination, overwrite=overwrite)
        fsync_directory(os.path.dirname(destination))
    finally:
        if created and os.path.lexists(stage):
            current = identity(stage)
            if current["inode"] == created[0]["inode"] and stat.S_ISREG(current["mode"]):
                os.unlink(stage)


def move_path_replacing_sync(source, destination, **kwargs):
    """覆盖事务：先准备新内容，再备份旧目标；所有提交窗口均可恢复。"""
    source, destination = os.path.abspath(source), os.path.abspath(destination)
    if os.path.normcase(source) == os.path.normcase(destination):
        return
    _validate_destination(source, destination)
    root = _journal_root()
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(source).encode()).hexdigest()
    path = root / (key + ".replacement.json")
    with _operation_lock(root / (key + ".lock")):
        if (root / (key + ".json")).exists():
            raise RuntimeError("来源存在普通移动记录，必须先恢复原操作")
        record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if record and record["destination"] != destination:
            raise RuntimeError("来源存在未完成替换，必须先恢复原目标")
        if record is None:
            operation_id = uuid.uuid4().hex
            record = {
                "version": 1, "kind": "replacement", "source": source, "destination": destination,
                "stage": destination + ".kikoerumanager-move-" + operation_id + ".part",
                "backup": destination + ".kikoerumanager-backup-" + operation_id,
                "source_manifest": snapshot(source),
                "old_manifest": snapshot(destination) if os.path.lexists(destination) else None,
                "state": "preparing",
            }
            atomic_json(path, record)
        _replace_locked(record, path, kwargs)


def _replace_locked(record, path, options):
    source, destination = record["source"], record["destination"]
    stage, backup = record["stage"], record["backup"]
    cancel = options.get("cancel_check")

    def check():
        _check_scope()
        if cancel and cancel():
            raise asyncio.CancelledError()

    def save(**fields):
        record.update(fields)
        atomic_json(path, record)

    if record["state"] == "preparing":
        check()
        if os.path.lexists(stage):
            # 来源重命名后、写阶段记录前崩溃；只能用完整 inode 清单确认。
            if os.path.lexists(source) or not _matches_published(
                    stage, record["source_manifest"], renamed=True):
                raise RuntimeError("替换准备中断，保留来源和暂存；核对后使用恢复工具重置")
            record["source_renamed"] = True
        else:
            try:
                publish_path(source, stage)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise

                def created(value):
                    save(stage_identity=value)

                def register(operation_id):
                    save(host_operations=record.get("host_operations", []) + [operation_id])

                copy_options = {k: v for k, v in options.items() if k in (
                    "progress_cb", "buffer_size", "progress_throttle_bytes", "phase_cb", "verify_hashes")}
                copy_path_exclusive_sync(source, stage, checkpoint=check, on_created=created,
                                         register_host_operation=register, **copy_options)
                record["source_renamed"] = False
            else:
                record["source_renamed"] = True
                _phase("重命名", source, stage, options.get("phase_cb"))
            fsync_directory(os.path.dirname(stage))
        save(state="staged", target_manifest=snapshot(stage))

    if record["state"] == "staged":
        check()
        if not _matches_published(stage, record["target_manifest"]):
            raise RuntimeError("替换暂存发生变化，拒绝提交")
        if not record["source_renamed"] and snapshot(source) != record["source_manifest"]:
            raise RuntimeError("替换来源发生变化，拒绝提交")
        old = record["old_manifest"]
        if old is not None:
            if os.path.lexists(backup):
                if os.path.lexists(destination) or not _matches_published(backup, old, renamed=True):
                    raise RuntimeError("无法确认替换备份归属，保留现场")
            else:
                if not _matches_published(destination, old):
                    raise RuntimeError("旧目标发生变化，拒绝替换")
                publish_path(destination, backup)
                fsync_directory(os.path.dirname(backup))
            record["backup_manifest"] = snapshot(backup)
        save(state="backed_up")

    if record["state"] == "backed_up":
        try:
            check()
            if os.path.lexists(stage):
                if not _matches_published(stage, record["target_manifest"]):
                    raise RuntimeError("替换暂存已变化，拒绝发布")
                publish_path(stage, destination)
                fsync_directory(os.path.dirname(destination))
            elif not os.path.lexists(destination) or not _matches_published(
                    destination, record["target_manifest"], renamed=True):
                raise RuntimeError("无法确认替换发布结果")
            save(state="published", target_manifest=snapshot(destination))
        except BaseException as exc:
            if not os.path.lexists(stage) and os.path.lexists(destination) and _matches_published(
                    destination, record["target_manifest"], renamed=True):
                raise MoveCleanupPending("替换已发布，保留旧备份等待恢复确认") from exc
            # 未发布时恢复旧目标；并发生成的目标绝不覆盖。
            if os.path.lexists(backup) and not os.path.lexists(destination):
                publish_path(backup, destination)
                save(state="staged", old_manifest=snapshot(destination))
            raise

    try:
        check()
        if not _matches_published(destination, record["target_manifest"]):
            raise RuntimeError("替换后的目标发生变化，拒绝清理")
        save(state="cleaning")
        if not record["source_renamed"]:
            _clean_source(source, record["source_manifest"], check)
        elif os.path.lexists(source):
            raise RuntimeError("来源路径被重新占用，保留备份等待核对")
        if record.get("backup_manifest"):
            _clean_source(backup, record["backup_manifest"], check)
        path.unlink()
        fsync_directory(str(path.parent))
    except Exception as exc:
        raise MoveCleanupPending("替换已发布，必须恢复清理，禁止再次覆盖目标") from exc


def move_config():
    from ..config.settings import get_config
    return get_config().file_move


def publish_path(source, destination, *, overwrite=False):
    """目标旁暂存的原子发布；无覆盖时禁止先 exists 再 replace 的竞争窗口。"""
    if overwrite:
        os.replace(source, destination)
        return
    if os.name == "nt":
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        result = renameat2(-100, ctypes.c_char_p(os.fsencode(source)),
                           -100, ctypes.c_char_p(os.fsencode(destination)), 1)
    else:
        import platform
        number = {"x86_64": 316, "aarch64": 276, "armv7l": 382, "i686": 353}.get(platform.machine())
        if number is None:
            raise OSError(errno.ENOTSUP, "当前平台不支持目录无覆盖原子发布")
        result = libc.syscall(number, -100, ctypes.c_char_p(os.fsencode(source)),
                              -100, ctypes.c_char_p(os.fsencode(destination)), 1)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), destination)


def snapshot(path):
    """不跟随符号链接，同时覆盖目录成员和身份；禁止特殊文件。"""
    result = {}

    def visit(current, relative):
        value = os.lstat(current)
        if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode)):
            raise ValueError("文件移动不支持设备、FIFO 或 socket: " + str(current))
        result[relative] = identity(current)
        if stat.S_ISLNK(value.st_mode):
            result[relative]["link"] = os.readlink(current)
        elif stat.S_ISDIR(value.st_mode):
            with os.scandir(current) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    visit(entry.path, entry.name if not relative else relative + "/" + entry.name)

    visit(str(path), "")
    return result


def _phase(name, source, destination, callback=None):
    logger.info("文件移动方式=%s 来源=%s 目标=%s", name, source, destination)
    if callback:
        callback(name)


def copy_path_exclusive_sync(source, destination, *, progress_cb=None, checkpoint=None,
                             buffer_size=BUFFER_SIZE, progress_throttle_bytes=4 * 1024 * 1024,
                             phase_cb=None, on_created=None, register_host_operation=None,
                             verify_hashes=False):
    """创建独占副本，不发布最终目标、不删来源；保留上层业务的校验与事务。"""
    source, destination = os.fspath(source), os.fspath(destination)
    def check():
        _check_scope()
        if checkpoint:
            checkpoint()
    check()
    frozen = snapshot(source)
    config = move_config()
    client = None
    mapping_version = None
    if config.host_enabled and any(stat.S_ISREG(row["mode"]) for row in frozen.values()):
        client = HostMoveClient(config.socket_path, config.request_timeout_seconds)
        capability = client.probe(source, os.path.dirname(os.path.abspath(destination)))
        mapping_version = capability["mapping_version"]
        if not capability["same_filesystem"]:
            client = None
    _phase("快速克隆" if client else "流式复制", source, destination, phase_cb)
    total = sum(row["size"] for row in frozen.values() if stat.S_ISREG(row["mode"]))
    completed, emitted = 0, 0
    hardlinks = {}

    def emit(force=False):
        nonlocal emitted
        if progress_cb and (force or completed - emitted >= progress_throttle_bytes):
            try:
                progress_cb(completed, total)
            except Exception:
                logger.debug("文件移动进度回调失败", exc_info=True)
            emitted = completed

    for relative, value in frozen.items():
        check()
        src = os.path.join(source, *relative.split("/")) if relative else source
        dst = os.path.join(destination, *relative.split("/")) if relative else destination
        mode = value["mode"]
        if stat.S_ISDIR(mode):
            os.mkdir(dst)
            if not relative and on_created:
                on_created(identity(dst))
        elif stat.S_ISLNK(mode):
            os.symlink(value["link"], dst, target_is_directory=os.path.isdir(src))
            if not relative and on_created:
                on_created(identity(dst))
        else:
            # st_dev 用于本次来源树内部硬链接识别，不用于跨子卷的文件系统判断。
            key = (os.lstat(src).st_dev, value["inode"])
            if key in hardlinks:
                os.link(hardlinks[key], dst)
                completed += value["size"]
            elif client:
                client.clone(src, dst, mapping_version, check, register_host_operation,
                             on_created=on_created if not relative else None)
                completed += value["size"]
                hardlinks[key] = dst
            else:
                with open(src, "rb", buffering=0) as reader, open(dst, "xb") as writer:
                    if not relative and on_created:
                        on_created(identity(dst))
                    while True:
                        check()
                        chunk = reader.read(buffer_size)
                        if not chunk:
                            break
                        writer.write(chunk)
                        completed += len(chunk)
                        emit()
                    writer.flush()
                    os.fsync(writer.fileno())
                hardlinks[key] = dst
            shutil.copystat(src, dst, follow_symlinks=False)
        emit()
    # 先处理子项，再恢复父目录时间和权限。
    for relative, value in reversed(list(frozen.items())):
        if stat.S_ISDIR(value["mode"]) or stat.S_ISLNK(value["mode"]):
            src = os.path.join(source, relative) if relative else source
            dst = os.path.join(destination, relative) if relative else destination
            shutil.copystat(src, dst, follow_symlinks=False)
            if stat.S_ISDIR(value["mode"]):
                fsync_directory(dst)
    check()
    _phase("校验", source, destination, phase_cb)
    if verify_hashes:
        for relative, value in frozen.items():
            if not stat.S_ISREG(value["mode"]):
                continue
            hashes = []
            for root in (source, destination):
                path = os.path.join(root, relative) if relative else root
                digest = hashlib.sha256()
                with open(path, "rb") as stream:
                    while True:
                        check()
                        chunk = stream.read(buffer_size)
                        if not chunk:
                            break
                        digest.update(chunk)
                hashes.append(digest.digest())
            if hashes[0] != hashes[1]:
                raise RuntimeError("文件 SHA-256 校验失败，保留来源及暂存")
    if snapshot(source) != frozen:
        raise RuntimeError("搬运期间来源发生变化，保留来源及暂存")
    target = snapshot(destination)
    if set(target) != set(frozen) or any(
        stat.S_IFMT(target[key]["mode"]) != stat.S_IFMT(value["mode"])
        or (stat.S_ISREG(value["mode"]) and target[key]["size"] != value["size"])
        or target[key].get("link") != value.get("link")
        for key, value in frozen.items()
    ):
        raise RuntimeError("搬运副本校验失败，保留来源及暂存")
    fsync_directory(os.path.dirname(os.path.abspath(destination)))
    emit(True)
    return frozen


def _journal_root():
    config = move_config()
    if config.journal_path:
        return Path(config.journal_path)
    from ..config.settings import get_config_file_path
    config_path = Path(get_config_file_path()).absolute()
    data = Path(os.environ["DATA_PATH"]) if os.environ.get("DATA_PATH") else (
        config_path.parent.parent if config_path.parent.parent.name == "data"
        else config_path.parent.parent / "data")
    return data / "file-moves"


@contextlib.contextmanager
def _operation_lock(path):
    with open(path, "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _matches_published(path, expected, *, renamed=False):
    actual = snapshot(path)
    # rename 会改变根 inode 的 ctime；其余身份、内容尺寸和全部成员必须一致。
    if renamed:
        actual = {**actual, "": {k: v for k, v in actual[""].items() if k != "ctime_ns"}}
        expected = {**expected, "": {k: v for k, v in expected[""].items() if k != "ctime_ns"}}
    return actual == expected


def _clean_source(source, manifest, checkpoint=None):
    """只删除清单中仍匹配的项；未知新成员由 rmdir 阻止删除。"""
    if not os.path.lexists(source):
        return
    remaining = snapshot(source)
    if not set(remaining).issubset(manifest):
        raise RuntimeError("来源出现清单外成员，拒绝清理")
    hardlinks = {}
    for row in manifest.values():
        if stat.S_ISREG(row["mode"]):
            key = (row["device"], row["inode"])
            hardlinks[key] = hardlinks.get(key, 0) + 1
    for relative, actual in remaining.items():
        expected = manifest[relative]
        fields = ("device", "inode", "mode") if stat.S_ISDIR(expected["mode"]) else (
            ("device", "inode", "mode", "mtime_ns", "size", "link")
            if hardlinks.get((expected["device"], expected["inode"]), 0) > 1
            else ("device", "inode", "mode", "mtime_ns", "ctime_ns", "size", "link"))
        if any(actual.get(field) != expected.get(field) for field in fields):
            raise RuntimeError("待清理来源身份已变化，保留现场")
    for relative, expected in reversed(list(manifest.items())):
        _check_scope()
        if checkpoint:
            checkpoint()
        path = os.path.join(source, *relative.split("/")) if relative else source
        if not os.path.lexists(path):
            continue
        actual = identity(path)
        if stat.S_ISDIR(expected["mode"]):
            if (actual["device"], actual["inode"]) != (expected["device"], expected["inode"]) or not stat.S_ISDIR(actual["mode"]):
                raise RuntimeError("来源目录身份已变化，拒绝清理")
            os.rmdir(path)
        else:
            if actual != {key: value for key, value in expected.items() if key != "link"}:
                # 删除一个硬链接会改变其它别名的 ctime，调用方在清理前已核对整个树。
                if not (hardlinks.get((expected["device"], expected["inode"]), 0) > 1 and
                        actual["device"] == expected["device"] and
                        actual["inode"] == expected["inode"] and
                        all(actual[key] == expected[key] for key in ("mode", "mtime_ns", "size"))):
                    raise RuntimeError("来源文件身份已变化，拒绝清理")
            os.unlink(path)
    fsync_directory(os.path.dirname(source))


def _validate_destination(source, destination):
    # 解析目标祖先，阻止通过符号链接将来源移入自己。
    resolved_source = os.path.normcase(os.path.realpath(source))
    resolved_destination = os.path.normcase(os.path.join(
        os.path.realpath(os.path.dirname(destination)), os.path.basename(destination)))
    try:
        inside = os.path.commonpath((resolved_source, resolved_destination)) == resolved_source
        ancestor = os.path.commonpath((resolved_source, resolved_destination)) == resolved_destination
    except ValueError:
        inside = False  # Windows 不同盘符。
        ancestor = False
    if inside or ancestor:
        raise ValueError("移动来源和目标不能互为祖先目录")


def move_path_sync(source, destination, *, overwrite=False, progress_cb=None, cancel_check=None,
                   buffer_size=BUFFER_SIZE, progress_throttle_bytes=4 * 1024 * 1024, phase_cb=None,
                   verify_hashes=False):
    source, destination = os.path.abspath(source), os.path.abspath(destination)
    if os.path.normcase(source) == os.path.normcase(destination):
        return
    _validate_destination(source, destination)
    root = _journal_root()
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(source).encode()).hexdigest()
    record_path = root / (key + ".json")

    def check():
        _check_scope()
        if cancel_check and cancel_check():
            raise asyncio.CancelledError()

    with _operation_lock(root / (key + ".lock")):
        if (root / (key + ".replacement.json")).exists():
            raise RuntimeError("来源存在未完成替换，必须先恢复替换操作")
        check()
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
        if record and (record["destination"] != destination or record["overwrite"] != overwrite):
            raise RuntimeError("来源存在未完成移动，请先恢复原目标操作")
        if record is None:
            # 精确目标语义；目录合并由业务层逐项调度。
            if not overwrite and os.path.lexists(destination):
                raise FileExistsError(errno.EEXIST, "移动目标已存在", destination)
            snapshot(source)  # 原生重命名前也拒绝特殊文件。
            try:
                publish_path(source, destination, overwrite=overwrite)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
            else:
                try:
                    _phase("重命名", source, destination, phase_cb)
                    fsync_directory(os.path.dirname(destination))
                    fsync_directory(os.path.dirname(source))
                except Exception as exc:
                    raise MoveCleanupPending("重命名已提交，后续确认失败，禁止回滚目标") from exc
                return
            operation_id = str(uuid.uuid4())
            record = {"version": 1, "source": source, "destination": destination, "overwrite": overwrite,
                      "stage": os.path.join(os.path.dirname(destination),
                                            ".kikoerumanager-move-" + operation_id + ".part"),
                      "state": "preparing", "source_manifest": snapshot(source)}
            atomic_json(record_path, record)
        stage = record["stage"]
        if record["state"] == "preparing":
            if os.path.lexists(stage):
                raise RuntimeError("存在中断移动暂存，保留现场；核对后使用恢复工具重置")
            def created(value):
                record["stage_identity"] = value
                atomic_json(record_path, record)

            def register(operation_id):
                record.setdefault("host_operations", []).append(operation_id)
                atomic_json(record_path, record)

            copy_path_exclusive_sync(
                source, stage, checkpoint=check, progress_cb=progress_cb, buffer_size=buffer_size,
                progress_throttle_bytes=progress_throttle_bytes, phase_cb=phase_cb,
                on_created=created, register_host_operation=register, verify_hashes=verify_hashes)
            if snapshot(source) != record["source_manifest"]:
                raise RuntimeError("来源在移动期间变化，拒绝发布")
            record.update(state="staged", target_manifest=snapshot(stage))
            atomic_json(record_path, record)
        check()
        if record["state"] == "staged":
            try:
                if os.path.lexists(stage):
                    if snapshot(source) != record["source_manifest"] or not _matches_published(stage, record["target_manifest"]):
                        raise RuntimeError("移动暂存或来源已变化，拒绝发布")
                    publish_path(stage, destination, overwrite=overwrite)
                    fsync_directory(os.path.dirname(destination))
                elif not os.path.lexists(destination) or not _matches_published(
                        destination, record["target_manifest"], renamed=True):
                    raise RuntimeError("无法确认中断移动的发布结果，拒绝删除来源")
                record.update(state="published", target_manifest=snapshot(destination))
                atomic_json(record_path, record)
            except Exception as exc:
                if not os.path.lexists(stage) and os.path.lexists(destination) and _matches_published(
                        destination, record["target_manifest"], renamed=True):
                    raise MoveCleanupPending("目标已发布，提交记录未完成；保留目标及来源等待恢复") from exc
                raise
        try:
            check()
            if not _matches_published(destination, record["target_manifest"]):
                raise RuntimeError("已发布目标发生变化，拒绝清理来源")
            if record["state"] == "published":
                if snapshot(source) != record["source_manifest"]:
                    raise RuntimeError("来源在发布后变化，拒绝清理")
                check()
                record["state"] = "cleaning"
                atomic_json(record_path, record)
            _phase("清理来源", source, destination, phase_cb)
            # 已提交后仅恢复清理；取消在逐项边界停止，保留 cleaning 记录。
            _clean_source(source, record["source_manifest"], check)
            record_path.unlink()
            fsync_directory(str(root))
        except Exception as exc:
            raise MoveCleanupPending("目标已发布，来源清理未完成；必须恢复原移动，禁止回滚目标") from exc


async def move_path_async(source, destination, **kwargs):
    """取消后等待实际线程停止，防止后台仍复制而前台已经回滚目录。"""
    return await run_file_operation_async(move_path_sync, source, destination, **kwargs)
