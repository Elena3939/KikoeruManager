"""文件移动运行态与只读诊断；不提供宿主命令或任意路径操作。"""
import itertools
import os
import time
from pathlib import Path

from .host_file_move_client import HostMoveClient, HostMoveError


def business_roots(config):
    storage = config.storage
    values = [getattr(storage, key, "") for key in (
        "input_path", "temp_path", "library_path", "processed_archives_path",
        "existing_folders_path", "asmr_subtitle_path")]
    values.extend(row.path for row in storage.libraries if row.enabled and row.type == "local")
    values.extend(getattr(config, name).download_root for name in ("http_downloader", "baidu_netdisk"))
    # 安装器也只授权这两个 data 子目录，不能扩大为整个 /app/data。
    if os.name == "posix":
        values.extend(("/app/data/filter-recovery", "/app/data/browser-uploads"))
    return sorted({os.path.normpath(value) for value in values if value})


def _within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _client(config):
    return HostMoveClient(config.file_move.socket_path,
                          min(config.file_move.request_timeout_seconds, 5))


def runtime_status(config):
    settings = config.file_move
    result = {"enabled": settings.host_enabled, "online": False, "ready": False,
              "settings": settings.model_dump(), "checked_at": time.time(),
              "roots": [], "service": None, "error": ""}
    try:
        service = _client(config).request("health")
        if not isinstance(service.get("mappings"), list) or not service.get("mapping_version"):
            raise HostMoveError("执行器缺少运行态能力，请更新宿主安装包")
        result.update(online=True, service=service)
        required = set(business_roots(config))
        paths = required | {row["path"] for row in service["mappings"]}
        for path in sorted(paths):
            mapping = next((row for row in sorted(service["mappings"],
                           key=lambda row: len(row["path"]), reverse=True)
                           if _within(path, row["path"])), None)
            result["roots"].append({
                "path": path, "configured": path in required, "mapped": mapping is not None,
                "available": bool(mapping and mapping.get("available")),
                "exists": os.path.isdir(path),
                "filesystem": mapping.get("filesystem", "") if mapping else "",
            })
        result["ready"] = bool(required) and all(
            row["mapped"] and row["available"] and row["exists"]
            for row in result["roots"] if row["configured"])
        if not result["ready"]:
            failed = [row["path"] for row in result["roots"] if row["configured"] and not (
                row["mapped"] and row["available"] and row["exists"])]
            result["error"] = ("部分业务目录未映射或不可访问，请同步容器挂载并检查目录："
                               + "、".join(failed))
    except (HostMoveError, ValueError, KeyError, TypeError) as exc:
        result["error"] = str(exc)
        result["roots"] = [{"path": path, "mapped": False, "available": False,
                            "exists": os.path.isdir(path), "filesystem": ""}
                           for path in business_roots(config)]
    return result


def validate_configuration_update(current, candidate):
    """仅在启用或搬运参数/业务目录改变时校验，关闭始终允许。"""
    if current.file_move.journal_path != candidate.file_move.journal_path:
        summary = journal_summary(current)
        if summary["sampled"]:
            raise ValueError("存在未完成搬运记录，不能更改恢复记录目录")
    if not candidate.file_move.host_enabled:
        return
    changed = (current.file_move.model_dump(exclude={"filter_verify_hashes"}) !=
               candidate.file_move.model_dump(exclude={"filter_verify_hashes"}) or
               business_roots(current) != business_roots(candidate))
    if not changed:
        return
    status = runtime_status(candidate)
    if not status["ready"]:
        raise ValueError("无法启用宿主加速：" + status["error"])


def probe_paths(config, source, destination):
    roots = business_roots(config)
    if source not in roots or destination not in roots:
        status = runtime_status(config)
        roots = {row["path"] for row in status["roots"]}
        if source not in roots or destination not in roots:
            raise ValueError("诊断仅允许选择当前配置或宿主已映射的业务根目录")
    probe = _client(config).probe(source, destination)
    return {**probe, "source": source, "destination": destination,
            "method": "快速克隆" if probe["same_filesystem"] else "流式复制",
            "note": "这是宿主文件系统身份检查；实际移动仍先尝试重命名。"
                    "同文件系统不代表已验证 FICLONE，需独立克隆验收。"}


def journal_summary(config):
    """有上限地查看恢复记录，不枚举业务文件、不触发恢复或删源。"""
    from .staged_file_move import _journal_root
    root = Path(config.file_move.journal_path) if config.file_move.journal_path else _journal_root()
    states = {}
    errors = 0
    scanned = 0
    truncated = False
    remaining = 16 * 1024 * 1024
    started = time.monotonic()
    if root.is_dir():
        import json
        with os.scandir(root) as entries:
            for entry in itertools.islice((e for e in entries if e.name.endswith(".json")), 501):
                scanned += 1
                if scanned > 500 or remaining <= 0 or time.monotonic() - started > 0.5:
                    truncated = True
                    break
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                    if not entry.is_file(follow_symlinks=False) or size > 8 * 1024 * 1024:
                        errors += 1
                        continue
                    if size > remaining:
                        truncated = True
                        break
                    with open(entry.path, "rb") as handle:
                        payload = handle.read(min(remaining, 8 * 1024 * 1024) + 1)
                    remaining -= len(payload)
                    if len(payload) > min(size, 8 * 1024 * 1024) or remaining < 0:
                        errors += 1
                        continue
                    record = json.loads(payload)
                    state = str(record.get("state", "unknown"))
                    states[state] = states.get(state, 0) + 1
                except (OSError, ValueError, AttributeError):
                    errors += 1
    return {"path": str(root), "states": states, "invalid": errors,
            "sampled": min(scanned, 500), "truncated": truncated}
