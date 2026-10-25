"""Linux 独立目录验收；不安装服务、不修改应用配置，只使用标准库。"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", required=True, type=Path)
    parser.add_argument("--docker", default="/var/packages/Docker/target/usr/bin/docker")
    parser.add_argument("--container", default="elena39-kikoerumanager")
    parser.add_argument("--pairs-json", required=True, type=Path,
                        help="inspect 已核对的 host_source/host_target/container_source/container_target 数组")
    parser.add_argument("--data-host", required=True)
    args = parser.parse_args()
    if args.container == "elena39-kikoerumanager":
        import socket
        if socket.gethostname() != "Elena":
            raise RuntimeError("生产主机身份不匹配")
    sys.path.insert(0, str(args.modules))
    from host_file_mover import Executor, mapping_digest
    from file_move_protocol import identity

    created = []
    process = None
    report = []
    try:
        workspace = Path(tempfile.mkdtemp(prefix="kikoerumanager-move-check-"))
        created.append(workspace)
        for pair in json.loads(args.pairs_json.read_text()):
            suffix = ".kikoerumanager-move-check-" + uuid.uuid4().hex
            source_root = Path(pair["host_source"]) / suffix
            target_root = Path(pair["host_target"]) / suffix
            for root in (source_root, target_root):
                root.mkdir(mode=0o700)
                created.append(root)
            mappings = [{"container": "/source", "host": str(source_root)},
                        {"container": "/target", "host": str(target_root)}]
            executor = Executor({"mappings": mappings, "records": str(workspace / suffix),
                                 "allowed_uid": os.getuid(), "allowed_gid": os.getgid()})
            source = source_root / "sample"
            source.write_bytes(os.urandom(4 * 1024 * 1024))
            probe = executor.probe({"source": "/source/sample", "destination_parent": "/target"})
            if not probe["same_filesystem"]:
                # 跨文件系统不得调用 FICLONE；验证应用的流式暂存和发布事务。
                sys.path.insert(0, str(args.modules.parent.parent))
                from types import SimpleNamespace
                from app.core import staged_file_move as moves
                config_before = moves.move_config
                class ProbeClient:
                    def __init__(self, *_args):
                        pass

                    def probe(self, *_args):
                        return probe

                    def clone(self, *_args, **_kwargs):
                        raise AssertionError("跨文件系统不应克隆")

                client_before = moves.HostMoveClient
                try:
                    moves.move_config = lambda: SimpleNamespace(host_enabled=True, socket_path="test",
                        request_timeout_seconds=1, journal_path=str(workspace / "journal"))
                    moves.HostMoveClient = ProbeClient
                    expected = digest(source)
                    target = target_root / "streamed"
                    phases = []
                    moves.move_path_sync(source, target, verify_hashes=True, phase_cb=phases.append)
                    assert not source.exists() and digest(target) == expected
                    assert "流式复制" in phases and "快速克隆" not in phases
                finally:
                    moves.move_config, moves.HostMoveClient = config_before, client_before
                report.append({"pair": pair["container_source"], "cross_filesystem_stream_hash": True})
                continue
            operation = str(uuid.uuid4())
            name = ".kikoerumanager-clone-" + operation + ".part"
            request = {"version": 1, "action": "prepare", "operation_id": operation,
                       "mapping_version": mapping_digest(mappings), "source": "/source/sample",
                       "destination": "/target/" + name, "source_identity": identity(source)}
            started = time.monotonic()
            result = executor.dispatch(request)
            target = target_root / name
            assert digest(source) == digest(target)
            assert executor.dispatch(request) == result
            with target.open("r+b") as stream:
                stream.write(b"COW")
            assert source.read_bytes()[:3] != b"COW"
            # 修改后的暂存必须拒绝清理，防误删其它写入。
            try:
                executor.dispatch({"version": 1, "action": "cancel", "operation_id": operation})
            except RuntimeError:
                pass
            else:
                raise AssertionError("变化后的暂存不应被执行器删除")
            for incoming in ("/source/../sample", "/source-other/sample"):
                try:
                    executor.probe({"source": incoming, "destination_parent": "/target"})
                except PermissionError:
                    pass
                else:
                    raise AssertionError("路径越界应拒绝")
            (source_root / "link").symlink_to(source_root, target_is_directory=True)
            try:
                executor.probe({"source": "/source/link/sample", "destination_parent": "/target"})
            except OSError:
                pass
            else:
                raise AssertionError("符号链接祖先应拒绝")
            # 在真实子卷间验证整树事务，而不只验证单文件 ioctl。
            sys.path.insert(0, str(args.modules.parent.parent))
            from types import SimpleNamespace
            from app.core import staged_file_move as moves
            from app.core.host_file_move_client import HostMoveClient

            class DirectClient(HostMoveClient):
                def __init__(self, *_args):
                    pass

                def request(self, action, **payload):
                    for field in ("source", "destination", "destination_parent"):
                        if field in payload:
                            for actual, virtual in ((str(source_root), "/source"), (str(target_root), "/target")):
                                if payload[field] == actual or payload[field].startswith(actual + "/"):
                                    payload[field] = virtual + payload[field][len(actual):]
                                    break
                    return executor.dispatch({"version": 1, "action": action, **payload})

            tree = source_root / "tree"
            tree.mkdir()
            (tree / "nested").mkdir()
            (tree / "nested/file").write_bytes(os.urandom(1024 * 1024))
            (tree / "empty").touch()
            os.link(tree / "nested/file", tree / "alias")
            (tree / "symbolic").symlink_to("nested/file")
            expected_hash = digest(tree / "alias")
            config_before, client_before = moves.move_config, moves.HostMoveClient
            try:
                moves.move_config = lambda: SimpleNamespace(host_enabled=True, socket_path="test",
                    request_timeout_seconds=1, journal_path=str(workspace / "tree-journal"))
                moves.HostMoveClient = DirectClient
                destination = target_root / "tree"
                phases = []
                moves.move_path_sync(tree, destination, verify_hashes=True, phase_cb=phases.append)
                assert not tree.exists() and digest(destination / "alias") == expected_hash
                assert (destination / "alias").stat().st_ino == (destination / "nested/file").stat().st_ino
                assert os.readlink(destination / "symbolic") == "nested/file"
                assert "快速克隆" in phases and "流式复制" not in phases
            finally:
                moves.move_config, moves.HostMoveClient = config_before, client_before
            report.append({"pair": pair["container_source"], "clone_hash_cow": True,
                           "tree_hash_hardlink_symlink": True,
                           "elapsed_seconds": round(time.monotonic() - started, 4)})

        # 临时前台进程验证真实容器 SO_PEERCRED/cgroup、Unix socket 和客户端协议。
        pair = json.loads(args.pairs_json.read_text())[0]
        suffix = ".kikoerumanager-socket-check-" + uuid.uuid4().hex
        left = Path(pair["host_source"]) / suffix
        right = Path(pair["host_target"]) / suffix
        for root in (left, right):
            root.mkdir(mode=0o700)
            created.append(root)
        container_left = pair["container_source"] + "/" + suffix
        container_right = pair["container_target"] + "/" + suffix
        for name in ("host_file_move_client.py", "file_move_protocol.py"):
            shutil.copy2(args.modules / name, left / name)
        (left / "sample").write_bytes(os.urandom(1024 * 1024))
        socket_directory = Path(args.data_host) / suffix
        # 只清理本次独占创建的通信目录。
        socket_directory.mkdir(mode=0o710)
        created.append(socket_directory)
        container_id = subprocess.check_output(
            [args.docker, "inspect", "--format", "{{.Id}}", args.container], universal_newlines=True).strip()
        uid = int(subprocess.check_output([args.docker, "exec", args.container, "id", "-u"]))
        gid = int(subprocess.check_output([args.docker, "exec", args.container, "id", "-g"]))
        config = {"mappings": [{"container": container_left, "host": str(left)},
                               {"container": container_right, "host": str(right)}],
                  "records": str(workspace / "socket-records"), "socket": str(socket_directory / "control.sock"),
                  "allowed_uid": uid, "allowed_gid": gid, "container_id": container_id}
        config_path = workspace / "socket-config.json"
        config_path.write_text(json.dumps(config))
        process = subprocess.Popen([sys.executable, str(args.modules / "host_file_mover.py"),
                                    "--config", str(config_path)])
        for _ in range(100):
            if (socket_directory / "control.sock").exists():
                break
            if process.poll() is not None:
                raise RuntimeError("临时执行器启动失败")
            time.sleep(0.05)
        script = (
            "import sys,types;"
            "p=types.ModuleType('move_check');p.__path__=[" + repr(container_left) + "];"
            "sys.modules['move_check']=p;"
            "from move_check.host_file_move_client import HostMoveClient;"
            "c=HostMoveClient(" + repr("/app/data/" + suffix + "/control.sock") + ");"
            "r=c.probe(" + repr(container_left + "/sample") + "," + repr(container_right) + ");"
            "c.clone(" + repr(container_left + "/sample") + "," + repr(container_right + "/copied") +
            ",r['mapping_version'],lambda:None)")
        subprocess.check_call([args.docker, "exec", args.container, "python3", "-c", script])
        assert digest(left / "sample") == digest(right / "copied")
        report.append({"socket_container_auth_clone": True})
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=60)
        for root in reversed(created):
            # 仅删除本次 mkdir/mkdtemp 成功登记的独占目录。
            if root.exists() and not root.is_symlink():
                shutil.rmtree(root)
        print("独立验收目录已清理；未安装服务、未修改生产配置")


if __name__ == "__main__":
    main()
