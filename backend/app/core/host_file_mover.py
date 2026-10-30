"""宿主常驻克隆执行器。支持 Python 3.8，不加载应用配置或第三方依赖。"""
import argparse
import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
import signal
import socket
import socketserver
import stat
import struct
import threading
import time
import weakref
from pathlib import Path, PurePosixPath

try:
    from .file_move_protocol import (
        VERSION, FICLONE, BTRFS_FS_INFO, atomic_json, check_regular,
        encode, fsync_directory, identity_stat, receive, token,
    )
except ImportError:
    from file_move_protocol import (
        VERSION, FICLONE, BTRFS_FS_INFO, atomic_json, check_regular,
        encode, fsync_directory, identity_stat, receive, token,
    )


def mapping_digest(mappings):
    return hashlib.sha256(json.dumps(mappings, sort_keys=True).encode()).hexdigest()


def filesystem_id(descriptor):
    """Btrfs 子卷的 st_dev 可以不同，必须从 ioctl 取真正的文件系统 UUID。"""
    buffer = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.fstatfs(descriptor, buffer) != 0:
        raise OSError(ctypes.get_errno(), "读取文件系统类型失败")
    fs_type = ctypes.c_ulong.from_buffer(buffer).value
    if fs_type == 0x9123683E:
        info = bytearray(1024)
        fcntl.ioctl(descriptor, BTRFS_FS_INFO, info, True)
        return "btrfs:" + bytes(info[16:32]).hex()
    return "{}:{}".format(fs_type, os.fstat(descriptor).st_dev)


def _mountpoints():
    with open("/proc/self/mountinfo", encoding="utf-8") as stream:
        return [line.split()[4].replace("\\040", " ").replace("\\134", "\\")
                for line in stream]


class Executor:
    def __init__(self, config):
        self.config = config
        self.mappings = sorted(config["mappings"], key=lambda row: len(row["container"]), reverse=True)
        self.mapping_version = mapping_digest(config["mappings"])
        self.records = Path(config["records"])
        self.records.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._guard = threading.Lock()
        self._locks = weakref.WeakValueDictionary()
        self.started_at = time.time()

    def health(self):
        """只返回容器白名单及能力，不暴露宿主路径或管理权限。"""
        mappings = []
        for row in self.mappings:
            item = {"path": row["container"]}
            try:
                with self.open_path(row["container"]) as (descriptor, _):
                    item["filesystem"] = filesystem_id(descriptor)
                item["available"] = True
            except OSError as exc:
                item.update(available=False, error=exc.strerror or type(exc).__name__)
            mappings.append(item)
        return {"protocol_version": VERSION, "mapping_version": self.mapping_version,
                "container_id": self.config["container_id"], "started_at": self.started_at,
                "capabilities": ["directory_transaction_v1"],
                "max_connections": 32, "max_executions": 4, "mappings": mappings}

    def _lock(self, operation_id):
        with self._guard:
            return self._locks.setdefault(operation_id, threading.Lock())

    @contextlib.contextmanager
    def open_path(self, incoming, *, parent=False):
        path = PurePosixPath(incoming)
        if not path.is_absolute() or ".." in path.parts or str(path) != incoming:
            raise PermissionError("路径必须是白名单内的规范绝对路径")
        selected = None
        for row in self.mappings:
            root = PurePosixPath(row["container"])
            if path == root or root in path.parents:
                selected = row
                break
        if selected is None:
            raise PermissionError("路径未列入宿主文件移动白名单")
        relative = path.relative_to(selected["container"])
        host_root = selected["host"]
        host_path = str(Path(host_root).joinpath(*relative.parts))
        for mounted in _mountpoints():
            if mounted != host_root and mounted.startswith(host_root.rstrip("/") + "/"):
                if host_path == mounted or host_path.startswith(mounted.rstrip("/") + "/"):
                    raise PermissionError("路径包含未声明的嵌套挂载")
        parts = relative.parts[:-1] if parent else relative.parts
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        descriptors = []
        try:
            # 白名单根本身的每一级也不允许被替换成符号链接。
            descriptor = os.open("/", flags)
            descriptors.append(descriptor)
            for part in Path(host_root).parts[1:]:
                descriptor = os.open(part, flags, dir_fd=descriptor)
                descriptors.append(descriptor)
            for index, part in enumerate(parts):
                mode = flags if parent or index < len(parts) - 1 else os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                descriptor = os.open(part, mode, dir_fd=descriptor)
                descriptors.append(descriptor)
            yield descriptor, relative.name
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _path(self, operation_id):
        return self.records / (token(operation_id) + ".json")

    def _read(self, operation_id):
        path = self._path(operation_id)
        return json.loads(path.read_text()) if path.exists() else None

    def _save(self, record):
        atomic_json(self._path(record["operation_id"]), record)

    def probe(self, request):
        with self.open_path(request["source"]) as (source, _):
            with self.open_path(request["destination_parent"]) as (parent, _):
                left, right = filesystem_id(source), filesystem_id(parent)
        return {"same_filesystem": left == right, "source_filesystem": left,
                "target_filesystem": right, "mapping_version": self.mapping_version,
                "capabilities": ["directory_transaction_v1"]}

    def directory_transaction(self, request):
        """目录暂存由应用持有；宿主只克隆成员，不发布、不删除整棵目录。"""
        operation_id = token(request["operation_id"])
        with self._lock(operation_id):
            record = self._read(operation_id)
            action = request["action"]
            if action == "begin_directory":
                parameters = {key: request[key] for key in
                              ("source", "destination", "mapping_version")}
                if parameters["mapping_version"] != self.mapping_version:
                    raise RuntimeError("宿主路径映射已变化")
                if record:
                    if record.get("kind") != "directory" or record.get("parameters") != parameters:
                        raise RuntimeError("目录事务 ID 或参数冲突")
                    if record["state"] != "preparing":
                        raise RuntimeError("目录事务已终止")
                    return record
                with self.open_path(parameters["source"]) as (source, _):
                    with self.open_path(parameters["destination"]) as (target, _):
                        if not stat.S_ISDIR(os.fstat(source).st_mode) or not stat.S_ISDIR(os.fstat(target).st_mode):
                            raise ValueError("目录事务要求独占暂存目录")
                        source_path = PurePosixPath(parameters["source"])
                        target_path = PurePosixPath(parameters["destination"])
                        if source_path == target_path or source_path in target_path.parents or target_path in source_path.parents:
                            raise ValueError("目录事务来源和暂存目录不能相互包含")
                        if os.listdir(target):
                            raise ValueError("目录事务暂存目录必须为空")
                        if filesystem_id(source) != filesystem_id(target):
                            raise RuntimeError("目录事务不能跨文件系统")
                        record = {
                            "operation_id": operation_id, "kind": "directory",
                            "parameters": parameters, "state": "preparing",
                            "source_identity": identity_stat(os.fstat(source)),
                            "destination_identity": identity_stat(os.fstat(target)),
                        }
                self._save(record)
                return record
            if not record or record.get("kind") != "directory":
                raise RuntimeError("目录事务不存在")
            if record["state"] != "preparing":
                raise RuntimeError("目录事务已结束，拒绝继续写入")
            parameters = record["parameters"]
            if parameters["mapping_version"] != self.mapping_version:
                raise RuntimeError("目录事务路径映射已变化")
            for key in ("source", "destination"):
                with self.open_path(parameters[key]) as (root, _):
                    actual = identity_stat(os.fstat(root))
                    expected = record[key + "_identity"]
                    if any(actual[field] != expected[field] for field in ("device", "inode")) or stat.S_IFMT(actual["mode"]) != stat.S_IFMT(expected["mode"]):
                        raise RuntimeError("目录事务根身份发生变化")
            if action == "finish_directory":
                record["state"] = "ready"
                self._save(record)
                return record
            if action != "prepare_member":
                raise ValueError("未知目录事务操作")
            source_path = PurePosixPath(request["source"])
            destination_path = PurePosixPath(request["destination"])
            source_relative = source_path.relative_to(parameters["source"])
            target_relative = destination_path.relative_to(parameters["destination"])
            if source_relative.parent != target_relative.parent:
                raise PermissionError("克隆成员不属于同一目录事务路径")
            member_id = token(request["member_id"])
            if destination_path.name != ".kikoerumanager-clone-" + member_id + ".part":
                raise PermissionError("目录成员必须使用独占克隆暂存名")
            started = time.monotonic()
            with self.open_path(str(source_path)) as (source, _):
                check_regular(os.fstat(source))
                if identity_stat(os.fstat(source)) != request["source_identity"]:
                    raise RuntimeError("目录成员来源已变化")
                with self.open_path(str(destination_path), parent=True) as (parent, name):
                    if filesystem_id(source) != filesystem_id(parent):
                        raise RuntimeError("目录成员跨文件系统")
                    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=parent)
                    try:
                        fcntl.ioctl(descriptor, FICLONE, source)
                        cloned = time.monotonic()
                        if identity_stat(os.fstat(source)) != request["source_identity"]:
                            raise RuntimeError("克隆期间来源发生变化")
                        os.fchown(descriptor, self.config["allowed_uid"], self.config["allowed_gid"])
                        os.fchmod(descriptor, stat.S_IMODE(os.fstat(source).st_mode))
                        # 应用恢复最终文件属性后执行文件 fsync，随后提交整树目录屏障。
                        result = identity_stat(os.fstat(descriptor))
                    finally:
                        os.close(descriptor)
            # 目录项由应用完成整树 fsync 屏障；中断只隔离暂存，绝不清理来源。
            for key in ("source", "destination"):
                with self.open_path(parameters[key]) as (root, _):
                    actual = identity_stat(os.fstat(root))
                    expected = record[key + "_identity"]
                    if any(actual[field] != expected[field] for field in ("device", "inode")):
                        raise RuntimeError("克隆期间目录事务根身份发生变化")
            return {"destination_identity": result,
                    "clone_seconds": cloned - started,
                    "sync_seconds": time.monotonic() - cloned}

    def prepare(self, request):
        operation_id = token(request["operation_id"])
        with self._lock(operation_id):
            if request["mapping_version"] != self.mapping_version:
                raise RuntimeError("宿主路径映射已变化，拒绝执行")
            old = self._read(operation_id)
            parameters = {key: request[key] for key in
                          ("source", "destination", "source_identity", "mapping_version")}
            if old:
                if old["state"] in ("cancelled", "released"):
                    raise RuntimeError("本次克隆操作已终止，拒绝重新执行")
                if old["parameters"] != parameters:
                    raise RuntimeError("同一操作 ID 的请求参数不一致")
                if old["state"] != "ready":
                    raise RuntimeError("上次克隆未完成，必须先取消并核对暂存")
                with self.open_path(parameters["destination"]) as (target, _):
                    if identity_stat(os.fstat(target)) != old["destination_identity"]:
                        raise RuntimeError("克隆暂存已变化")
                return old
            expected_name = ".kikoerumanager-clone-" + operation_id + ".part"
            if PurePosixPath(parameters["destination"]).name != expected_name:
                raise PermissionError("执行器只允许写入本次操作的专属暂存")
            record = {"operation_id": operation_id, "parameters": parameters, "state": "preparing"}
            self._save(record)
            try:
                with self.open_path(parameters["source"]) as (source, _):
                    check_regular(os.fstat(source))
                    if identity_stat(os.fstat(source)) != parameters["source_identity"]:
                        raise RuntimeError("克隆来源身份已变化")
                    with self.open_path(parameters["destination"], parent=True) as (parent, name):
                        if filesystem_id(source) != filesystem_id(parent):
                            raise RuntimeError("跨文件系统不能克隆，拒绝隐式复制")
                        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                             0o600, dir_fd=parent)
                        try:
                            record["created_identity"] = identity_stat(os.fstat(descriptor))
                            self._save(record)
                            fcntl.ioctl(descriptor, FICLONE, source)
                            if identity_stat(os.fstat(source)) != parameters["source_identity"]:
                                raise RuntimeError("克隆期间来源发生变化")
                            os.fchown(descriptor, self.config["allowed_uid"], self.config["allowed_gid"])
                            os.fchmod(descriptor, stat.S_IMODE(os.fstat(source).st_mode))
                            os.fsync(descriptor)
                            record["destination_identity"] = identity_stat(os.fstat(descriptor))
                        finally:
                            os.close(descriptor)
                        os.fsync(parent)
                record["state"] = "ready"
                self._save(record)
                return record
            except BaseException:
                record["state"] = "interrupted"
                self._save(record)
                raise

    def control(self, request):
        operation_id = token(request["operation_id"])
        with self._lock(operation_id):
            record = self._read(operation_id)
            if not record:
                if request["action"] == "cancel":
                    # 取消可能先于排队中的 prepare 获得操作锁，必须阻止它随后启动。
                    self._save({"operation_id": operation_id, "state": "cancelled"})
                    return {"state": "cancelled"}
                return {"state": "absent"}
            if request["action"] == "status":
                return record
            if record["state"] in ("cancelled", "released"):
                return {"state": record["state"]}
            if record.get("kind") == "directory":
                # 与成员操作共用锁；终态落盘后不再接受任何成员写入。
                # 所有暂存保留给应用按根身份隔离，不猜测崩溃前的成员归属。
                record["state"] = "cancelled" if request["action"] == "cancel" else "released"
                self._save(record)
                return {"state": record["state"]}
            destination = record["parameters"]["destination"]
            try:
                with self.open_path(destination, parent=True) as (parent, name):
                    try:
                        value = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        value = None
                    if value:
                        expected = record.get("destination_identity") or record.get("created_identity")
                        if not expected or (value.st_dev, value.st_ino) != (expected["device"], expected["inode"]) or not stat.S_ISREG(value.st_mode):
                            raise RuntimeError("暂存归属无法确认，拒绝清理")
                        if record.get("destination_identity") and identity_stat(value) != expected:
                            raise RuntimeError("已完成暂存身份变化，拒绝清理")
                        if request["action"] == "release":
                            raise RuntimeError("暂存尚未发布，不能释放记录")
                        os.unlink(name, dir_fd=parent)
                        os.fsync(parent)
            except FileNotFoundError:
                pass
            # 保留终态，避免同一 ID 在重试时重新创建克隆暂存。
            record["state"] = "cancelled" if request["action"] == "cancel" else "released"
            self._save(record)
            return {"state": record["state"]}

    def dispatch(self, request):
        if request.get("version") != VERSION:
            raise ValueError("文件移动协议版本不匹配")
        action = request.get("action")
        if action == "health":
            return self.health()
        if action == "probe":
            return self.probe(request)
        if action == "prepare":
            return self.prepare(request)
        if action in ("begin_directory", "prepare_member", "finish_directory"):
            return self.directory_transaction(request)
        if action in ("status", "cancel", "release"):
            return self.control(request)
        raise ValueError("未知文件移动操作")


class Handler(socketserver.StreamRequestHandler):
    heartbeat_seconds = 1

    def dispatch_request(self, request):
        # 控制请求不能排在克隆执行槽后面；同一操作仍由操作锁等待安全确认。
        if request.get("action") in {"status", "cancel", "release"}:
            return self.server.executor.dispatch(request)
        with self.server.slots:
            return self.server.executor.dispatch(request)

    def handle(self):
        self.request.settimeout(60)
        try:
            pid, uid, _gid = struct.unpack("3i", self.request.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            config = self.server.executor.config
            if uid != config["allowed_uid"]:
                raise PermissionError("文件移动客户端 UID 不匹配")
            container_id = config["container_id"]
            with open("/proc/{}/cgroup".format(pid), encoding="utf-8") as stream:
                groups = stream.read()
            components = groups.replace(".scope", "").replace("docker-", "/").replace("\n", "/").split("/")
            if container_id not in components:
                raise PermissionError("文件移动客户端不属于指定容器")
            request = receive(self.rfile)
            if request.get("keepalive"):
                result = self.dispatch_with_keepalive(request)
            else:
                result = self.dispatch_request(request)
            response = {"version": VERSION, "ok": True, "result": result}
        except Exception as exc:
            response = {"version": VERSION, "ok": False, "error": str(exc)}
        try:
            self.wfile.write(encode(response))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def dispatch_with_keepalive(self, request):
        """排队和磁盘同步期间定期响应；断线不撤销正在执行的文件事务。"""
        done = threading.Event()
        outcome = {}

        def execute():
            try:
                outcome["result"] = self.dispatch_request(request)
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(target=execute)
        worker.start()
        while not done.wait(self.heartbeat_seconds):
            try:
                self.wfile.write(encode({"version": VERSION, "pending": True}))
            except (OSError, ValueError):
                # ioctl 不可安全中断；完成后仍由操作记录供 cancel/recovery 核对。
                worker.join()
                raise
        worker.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(4)
        self.connections = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

def open_directory(path):
    """逐级打开宿主目录，连映射根的祖先也不能是符号链接。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def main():
    parser = argparse.ArgumentParser(description="KikoeruManager 宿主克隆执行器")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    socket_path = Path(config["socket"])
    executor = Executor(config)
    # data 挂载由应用写入；仅通过目录描述符创建/打开通信目录，不能跟随伪造链接。
    parent = open_directory(socket_path.parent.parent)
    try:
        try:
            os.mkdir(socket_path.parent.name, 0o710, dir_fd=parent)
        except FileExistsError:
            pass
        directory = os.open(socket_path.parent.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
    finally:
        os.close(parent)
    if os.fstat(directory).st_uid != 0:
        os.close(directory)
        raise PermissionError("通信目录必须由 root 创建并管理")
    os.fchown(directory, 0, config["allowed_gid"])
    os.fchmod(directory, 0o710)
    # 不允许多实例删除另一个正在服务的 socket。
    with open(executor.records / "service.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            previous = os.stat(socket_path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            previous = None
        if previous:
            if not stat.S_ISSOCK(previous.st_mode):
                raise RuntimeError("通信路径被非 socket 对象占用")
            os.unlink(socket_path.name, dir_fd=directory)
        # bind 使用持有的目录 inode；应用重命名父目录只会导致连接失败，不能诱导 root 写其它路径。
        with Server("/proc/self/fd/{}/{}".format(directory, socket_path.name), Handler) as server:
            server.executor = executor
            os.chown(socket_path.name, config["allowed_uid"], config["allowed_gid"],
                     dir_fd=directory, follow_symlinks=False)
            os.chmod(socket_path.name, 0o600, dir_fd=directory)
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: threading.Thread(target=server.shutdown).start())
            try:
                server.serve_forever()
            finally:
                os.unlink(socket_path.name, dir_fd=directory)
                os.close(directory)


if __name__ == "__main__":
    main()
