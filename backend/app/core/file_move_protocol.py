"""宿主文件克隆协议。仅依赖标准库，供宿主 Python 3.8 共用。"""
import json
import os
import stat
import uuid

VERSION = 1
MAX_MESSAGE = 1024 * 1024
FICLONE = 0x40049409
BTRFS_FS_INFO = 0x8400941F


def identity(path):
    return identity_stat(os.lstat(path))


def identity_stat(value):
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "mode": value.st_mode,
    }


def check_regular(value):
    if not stat.S_ISREG(value.st_mode):
        raise ValueError("克隆来源必须是普通文件")


def token(value):
    if str(uuid.UUID(str(value))) != value:
        raise ValueError("操作 ID 无效")
    return value


def encode(value):
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        raise ValueError("文件移动协议消息过大")
    return data


def receive(stream):
    data = stream.readline(MAX_MESSAGE + 1)
    if not data.endswith(b"\n") or len(data) > MAX_MESSAGE:
        raise ValueError("文件移动协议消息不完整或过大")
    return json.loads(data)


def atomic_json(path, value):
    temporary = str(path) + "." + uuid.uuid4().hex + ".tmp"
    try:
        with open(temporary, "x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(os.path.dirname(str(path)))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fsync_directory(path):
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
