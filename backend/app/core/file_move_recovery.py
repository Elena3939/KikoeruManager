"""文件移动恢复工具：列出状态、继续提交/清源、隔离准备中的残留。"""
import argparse
import hashlib
import json
import os
import uuid

from .file_move_protocol import fsync_directory, identity
from .host_file_move_client import HostMoveClient
from .staged_file_move import (
    _journal_root, _operation_lock, move_config, move_path_sync, move_path_replacing_sync,
    publish_path, snapshot,
)


def records():
    root = _journal_root()
    if not root.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))]


def restart_preparing(source):
    """确认执行器停止后隔离残留；不自动删除无法证明完整归属的目录成员。"""
    source = os.path.abspath(source)
    root = _journal_root()
    key = hashlib.sha256(os.path.normcase(source).encode()).hexdigest()
    path = root / (key + ".json")
    if not path.exists():
        path = root / (key + ".replacement.json")
    with _operation_lock(root / (key + ".lock")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["source"] != source or record["state"] != "preparing":
            raise RuntimeError("仅准备阶段允许重新开始；已暂存/发布操作必须继续原操作")
        if snapshot(source) != record["source_manifest"]:
            raise RuntimeError("来源已变化，保留全部现场等待人工核对")
        operations = record.get("host_operations", [])
        if operations:
            config = move_config()
            client = HostMoveClient(config.socket_path, config.request_timeout_seconds)
            for operation_id in operations:
                client.request("cancel", operation_id=operation_id)
        stage = record["stage"]
        quarantined = None
        if os.path.lexists(stage):
            expected = record.get("stage_identity")
            actual = identity(stage)
            if not expected or any(actual[key] != expected[key] for key in ("device", "inode", "mode")):
                raise RuntimeError("无法确认暂存根身份，保留现场")
            quarantined = stage + ".interrupted-" + uuid.uuid4().hex
            publish_path(stage, quarantined)
            fsync_directory(os.path.dirname(stage))
        path.unlink()
        fsync_directory(str(root))
        return quarantined


def main():
    parser = argparse.ArgumentParser(description="文件移动恢复；须在相关业务任务停止后运行")
    parser.add_argument("action", choices=("status", "resume", "restart-preparing"))
    parser.add_argument("--source")
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps(records(), ensure_ascii=False, indent=2))
        return
    if not args.source:
        parser.error("恢复操作必须指定 --source")
    if args.action == "restart-preparing":
        print(json.dumps({"quarantined": restart_preparing(args.source)}, ensure_ascii=False))
        return
    source = os.path.abspath(args.source)
    matches = [row for row in records() if row["source"] == source]
    if len(matches) != 1:
        raise RuntimeError("没有唯一的待恢复记录")
    row = matches[0]
    if row.get("kind") == "replacement":
        move_path_replacing_sync(source, row["destination"])
    else:
        move_path_sync(source, row["destination"], overwrite=row["overwrite"])


if __name__ == "__main__":
    main()
