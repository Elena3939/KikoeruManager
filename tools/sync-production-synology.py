"""将群晖生产容器登记同步到 Docker 当前身份。"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


def main():
    if socket.gethostname() != "Elena":
        raise RuntimeError("生产主机校验失败")
    name = "elena39-kikoerumanager"
    docker = "/var/packages/Docker/target/usr/bin/docker"
    current = json.loads(subprocess.check_output([docker, "inspect", name]))[0]
    path = Path("/var/packages/Docker/etc") / (name + ".config")
    previous = path.read_bytes()
    config = json.loads(previous)
    if config.get("name") != name or current["Name"] != "/" + name:
        raise RuntimeError("容器登记名称不匹配")
    backup = Path(sys.argv[1])
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_file = backup / "synology-registration-before.json"
    if not backup_file.exists():
        backup_file.write_bytes(previous)
        backup_file.chmod(0o600)
    config.update(id=current["Id"], image=current["Config"]["Image"])
    stat = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=str(path.parent),
                                         prefix=".kikoerumanager-", delete=False) as stream:
            temporary = stream.name
            json.dump(config, stream, ensure_ascii=False, indent=3)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.st_mode & 0o777)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    response = json.loads(subprocess.check_output([
        "/usr/syno/bin/synowebapi", "--exec", "api=SYNO.Docker.Container",
        "method=list", "version=1", "limit=1000", "offset=0",
    ], stderr=subprocess.DEVNULL))
    registered = [item for item in response.get("data", {}).get("containers", [])
                  if item.get("name") == name]
    if not response.get("success") or len(registered) != 1:
        raise RuntimeError("群晖容器列表未返回唯一生产登记")
    if registered[0].get("id") != current["Id"]:
        raise RuntimeError("群晖容器 ID 校验失败")
    if current["State"]["Running"] and registered[0].get("status") != "running":
        raise RuntimeError("群晖容器运行状态校验失败")
    print("群晖登记已核对: " + current["Id"] + " " + registered[0]["status"])


if __name__ == "__main__":
    main()
