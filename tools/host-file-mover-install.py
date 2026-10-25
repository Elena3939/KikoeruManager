"""生成宿主执行器安装包；显式 --install 才写 systemd。仅依赖 Python 3.8 标准库。"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

FILES = ("host_file_mover.py", "file_move_protocol.py")
SERVICE = "kikoerumanager-file-mover.service"
UNIT = """[Unit]
Description=KikoeruManager 宿主文件克隆执行器
After=docker.service

[Service]
Type=simple
ExecStart={python} {root}/current/host_file_mover.py --config {root}/current/config.json
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
KillMode=control-group
TimeoutStopSec=3600

[Install]
WantedBy=multi-user.target
"""


def within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def canonical(path):
    if not isinstance(path, str) or not path.startswith("/") or posixpath.normpath(path) != path:
        raise ValueError("业务路径必须是规范的容器绝对路径")
    return path


def installation_root(root):
    canonical(root)
    if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", root) or root in ("/", "/var", "/var/lib"):
        raise ValueError("安装目录必须是独立的无空格、无 systemd 转义字符绝对路径")
    return root


def business_paths(config):
    """从应用配置提取路径；不输出密码、Token 或其它配置内容。"""
    storage = config["storage"]
    values = [storage.get(key, "") for key in (
        "input_path", "temp_path", "library_path", "processed_archives_path",
        "existing_folders_path", "asmr_subtitle_path")]
    for library in storage.get("libraries", []):
        if library.get("type", "local") == "local" and library.get("enabled", True):
            values.append(library.get("path", ""))
    for section in ("http_downloader", "baidu_netdisk"):
        values.append(config.get(section, {}).get("download_root", ""))
    values.append("/app/data/filter-recovery")
    values.append("/app/data/browser-uploads")
    return sorted({canonical(value) for value in values if value})


def validate_business_path(path):
    canonical(path)
    forbidden = ("/app/config", "/app/postgres", "/app/app", "/app/static",
                 "/proc", "/sys", "/dev", "/etc", "/var/run", "/run",
                 "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/root", "/var/lib")
    if path == "/" or path in ("/app", "/app/data") or any(
            within(path, item) or within(item, path) for item in forbidden):
        raise ValueError("禁止映射配置、数据库、代码或系统目录: " + path)
    if within(path, "/app/data") and not any(
            within(path, item) for item in ("/app/data/filter-recovery", "/app/data/browser-uploads")):
        raise ValueError("data 仅允许明确的上传和过滤恢复子目录: " + path)


def mounted_business_paths(inspected):
    """同步实际可写业务挂载，不依赖当前设置选中了哪个目录。"""
    paths = set()
    for mount in inspected["Mounts"]:
        if mount["Type"] != "bind" or not mount.get("RW"):
            continue
        path = mount["Destination"]
        if path == "/app/data":
            paths.update(("/app/data/filter-recovery", "/app/data/browser-uploads"))
            continue
        try:
            validate_business_path(path)
        except ValueError:
            continue
        paths.add(path)
    return sorted(paths)


def build_config(inspected, paths, uid, gid, root):
    """按边界及最长挂载前缀映射；不接受手写宿主路径。"""
    installation_root(root)
    if uid < 0 or gid < 0:
        raise ValueError("UID 和 GID 不能为负数")
    if inspected.get("HostConfig", {}).get("UsernsMode") not in ("", "host", None):
        raise ValueError("不支持用户命名空间重映射")
    container_id = inspected["Id"]
    if len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id):
        raise ValueError("inspect 容器 ID 无效")
    mounts = sorted(inspected["Mounts"], key=lambda row: len(row["Destination"]), reverse=True)
    mappings = []
    for path in sorted(set(paths)):
        validate_business_path(path)
        mounted = next((row for row in mounts if within(path, row["Destination"])), None)
        if not mounted or mounted["Type"] != "bind" or not mounted.get("RW"):
            raise ValueError("业务路径没有可写 bind 挂载: " + path)
        # 子挂载必须显式独立映射，不能在父映射中穿越。
        for child in mounts:
            nested = child["Destination"]
            if nested != mounted["Destination"] and within(nested, path) and nested not in paths:
                raise ValueError("业务目录包含未声明的嵌套挂载: " + nested)
        relative = posixpath.relpath(path, mounted["Destination"])
        host = mounted["Source"] if relative == "." else posixpath.join(mounted["Source"], relative)
        mappings.append({"container": path, "host": host})
    if not mappings:
        raise ValueError("必须明确指定业务白名单，不能推测全部挂载都可搬运")
    data = next((row for row in mounts if row["Destination"] == "/app/data"), None)
    if not data or data["Type"] != "bind" or not data.get("RW"):
        raise ValueError("必须已有 /app/data 可写 bind 挂载")
    return {"mappings": mappings, "container_id": container_id, "allowed_uid": int(uid),
            "allowed_gid": int(gid), "records": root + "/records",
            "socket": posixpath.join(data["Source"], ".host-file-mover/control.sock")}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_bundle(output, inspected, paths, uid, gid, root, sources, host_python="/bin/python3"):
    canonical(host_python)
    if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", host_python):
        raise ValueError("宿主 Python 路径包含不支持的 systemd 字符")
    paths = sorted(set(paths) | set(mounted_business_paths(inspected)))
    config = build_config(inspected, paths, uid, gid, root)
    output.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        shutil.copy2(sources / name, output / name)
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=True, indent=2), encoding="utf-8")
    (output / SERVICE).write_text(UNIT.format(root=root, python=host_python), encoding="utf-8")
    manifest = {"version": 1, "release": "file-mover-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
                "container_id": config["container_id"],
                "sha256": {p.name: sha(p) for p in sorted(output.iterdir())}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return config


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def install(bundle, root, container, docker, production=False):
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("安装必须在 Linux 宿主由 root 显式执行")
    installation_root(str(root))
    if (production or container == "elena39-kikoerumanager") and (
            socket.gethostname() != "Elena" or container != "elena39-kikoerumanager"):
        raise RuntimeError("生产主机或容器不匹配")
    manifest = json.loads((bundle / "manifest.json").read_text())
    expected_files = {*FILES, "config.json", SERVICE}
    if (set(manifest["sha256"]) != expected_files or
            {p.name for p in bundle.iterdir()} != expected_files | {"manifest.json"} or
            any(p.is_symlink() or not p.is_file() for p in bundle.iterdir())):
        raise RuntimeError("安装包文件清单不完整或包含额外文件/符号链接")
    release_id = manifest["release"]
    if not re.fullmatch(r"file-mover-\d{8}-\d{6}", release_id):
        raise RuntimeError("安装版本号无效")
    for name, expected in manifest["sha256"].items():
        if name not in (*FILES, "config.json", SERVICE) or sha(bundle / name) != expected:
            raise RuntimeError("安装包 SHA-256 校验失败")
    config = json.loads((bundle / "config.json").read_text())
    command = next(line[len("ExecStart="):] for line in (bundle / SERVICE).read_text().splitlines()
                   if line.startswith("ExecStart="))
    host_python = command.split(" ", 1)[0]
    if command != UNIT.format(root=root, python=host_python).split("ExecStart=", 1)[1].splitlines()[0]:
        raise RuntimeError("服务启动命令不匹配受支持的执行器入口")
    canonical(host_python)
    if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", host_python):
        raise RuntimeError("宿主 Python 路径无效")
    version = json.loads(run(host_python, "-c", "import json,sys;print(json.dumps(list(sys.version_info[:2])))"))
    if tuple(version) < (3, 8):
        raise RuntimeError("宿主执行器要求 Python 3.8 或更新版本")
    inspected = json.loads(run(docker, "inspect", container))[0]
    uid = int(run(docker, "exec", container, "id", "-u"))
    gid = int(run(docker, "exec", container, "id", "-g"))
    actual = build_config(inspected, [r["container"] for r in config["mappings"]], uid, gid, str(root))
    if config != actual or inspected["Id"] != manifest["container_id"]:
        raise RuntimeError("真实容器、运行 UID 或映射变化，必须重新生成安装包")
    info = json.loads(run(docker, "info", "--format", "{{json .SecurityOptions}}"))
    if any("userns" in item for item in info):
        raise RuntimeError("Docker 开启全局用户命名空间重映射，拒绝安装")
    for row in config["mappings"]:
        host = row["host"]
        if os.path.realpath(host) != host or not os.path.isdir(host):
            raise RuntimeError("宿主业务目录不存在或包含符号链接: " + host)
    if os.path.realpath(root) != str(root):
        raise RuntimeError("安装目录祖先不能包含符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
        raise RuntimeError("安装根目录必须由 root 独占写入")
    versions = root / "versions"
    versions.mkdir(mode=0o700, exist_ok=True)
    if versions.is_symlink() or versions.stat().st_uid != 0 or versions.stat().st_mode & 0o022:
        raise RuntimeError("版本目录必须由 root 独占写入")
    release = versions / manifest["release"]
    shutil.copytree(bundle, release)
    os.chmod(release, 0o700)
    for path in release.iterdir():
        os.chmod(path, 0o600)
    previous = os.readlink(root / "current") if (root / "current").is_symlink() else None
    if previous and (not within(os.path.realpath(root / "current"), str(versions))):
        raise RuntimeError("当前版本链接必须指向受管理版本目录")
    unit = Path("/etc/systemd/system") / SERVICE
    previous_unit = unit.read_bytes() if unit.exists() else None
    was_enabled = subprocess.call(["systemctl", "is-enabled", "--quiet", SERVICE]) == 0
    candidate = root / "current.next"
    if candidate.exists() or candidate.is_symlink():
        candidate.unlink()
    candidate.symlink_to(release)
    try:
        os.replace(candidate, root / "current")
        unit.write_bytes((release / SERVICE).read_bytes())
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", SERVICE)
        run("systemctl", "restart", SERVICE)
        run("systemctl", "is-active", "--quiet", SERVICE)
        # 从真实容器身份连接 socket；active 不能证明映射和鉴权有效。
        pairs = [(r["container"], r["container"]) for r in config["mappings"]
                 if os.path.isdir(r["host"])]
        if not pairs:
            raise RuntimeError("没有可用于容器能力验证的业务目录")
        probe_code = (
            "from app.core.host_file_move_client import HostMoveClient;"
            "import json;"
            "c=HostMoveClient('/app/data/.host-file-mover/control.sock');"
            "print(json.dumps([c.probe(a,b) for a,b in " + repr(pairs) + "]))")
        # systemd active 只表示进程已启动，socket 可能尚未完成绑定和权限设置。
        deadline = time.monotonic() + 15
        while True:
            try:
                probes = json.loads(run(docker, "exec", container, "python3", "-c", probe_code))
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        digest = hashlib.sha256(json.dumps(config["mappings"], sort_keys=True).encode()).hexdigest()
        if not probes or any(row["mapping_version"] != digest for row in probes):
            raise RuntimeError("执行器能力验证返回了其它映射版本")
    except BaseException:
        if previous:
            candidate.symlink_to(previous)
            os.replace(candidate, root / "current")
        else:
            (root / "current").unlink(missing_ok=True)
        if previous_unit is not None:
            unit.write_bytes(previous_unit)
        else:
            unit.unlink(missing_ok=True)
        run("systemctl", "daemon-reload")
        if previous:
            run("systemctl", "restart", SERVICE)
        else:
            run("systemctl", "disable", "--now", SERVICE)
        if not was_enabled:
            run("systemctl", "disable", SERVICE)
        raise
    for old in sorted(versions.iterdir(), key=lambda p: p.name, reverse=True)[3:]:
        if old != release:
            shutil.rmtree(old)
    print("执行器已安装；应用 host_enabled 未修改，须独立验收后显式启用")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-json", type=Path)
    parser.add_argument("--paths-json", type=Path, help="明确业务容器路径的 JSON 数组")
    parser.add_argument("--app-config-json", type=Path, help="应用配置 JSON；仅提取业务路径，不打包原配置")
    parser.add_argument("--uid", type=int)
    parser.add_argument("--gid", type=int)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--root", default="/var/lib/kikoerumanager-file-mover")
    parser.add_argument("--host-python", default="/bin/python3", help="已核实的宿主 Python 3.8+ 绝对路径；安装前实测版本")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--container", default="elena39-kikoerumanager")
    parser.add_argument("--docker", default="/var/packages/Docker/target/usr/bin/docker")
    args = parser.parse_args()
    canonical(args.root)
    if args.install:
        install(args.bundle, Path(args.root), args.container, args.docker, args.production)
    else:
        if args.inspect_json is None or args.uid is None or args.gid is None:
            parser.error("准备安装包需要 inspect 及 UID/GID")
        inspected = json.loads(args.inspect_json.read_text(encoding="utf-8-sig"))
        if isinstance(inspected, list):
            if len(inspected) != 1:
                parser.error("inspect 必须只包含目标容器")
            inspected = inspected[0]
        paths = (business_paths(json.loads(args.app_config_json.read_text(encoding="utf-8-sig")))
                 if args.app_config_json else
                 json.loads(args.paths_json.read_text(encoding="utf-8-sig")) if args.paths_json else [])
        make_bundle(args.bundle, inspected, paths,
                    args.uid, args.gid, args.root, Path(__file__).resolve().parents[1] / "backend/app/core",
                    args.host_python)
        print("已生成可审查安装包；未安装服务或修改应用配置")


if __name__ == "__main__":
    main()
