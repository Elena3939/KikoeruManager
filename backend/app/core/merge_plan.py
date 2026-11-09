"""合并计划与一次性目录构建；只操作独占暂存，不发布库存。"""
import os
import shutil
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from .file_move_protocol import fsync_directory, identity
from .host_file_move_client import HostMoveClient
from .staged_file_move import BUFFER_SIZE, _check_scope, move_config, snapshot


class ComparedItems(list):
    def __init__(self, items, source_manifest, existing_manifest):
        super().__init__(items)
        self.source_manifest = source_manifest
        self.existing_manifest = existing_manifest


def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value or ":" in value:
        raise ValueError("合并成员路径无效")
    return value


def validate_manifest(root, expected):
    if expected is None or snapshot(root) != expected:
        raise ValueError("合并预览后目录已变化，请刷新差异后重新提交")


@dataclass
class MergePlan:
    roots: dict
    manifests: dict
    files: dict
    directories: dict
    deleted: list
    unchanged: bool
    total_bytes: int

    @property
    def uses_new(self):
        return any(row["root"] == "new" for row in self.files.values())

    def validate(self):
        for key, root in self.roots.items():
            validate_manifest(root, self.manifests[key])

    def rebind_new(self, root, before_filter):
        """过滤保持完整上下文，但已选文件不能被过滤删除或改写。"""
        current = snapshot(root)
        previous = self.manifests["new"]
        for relative, row in self.files.items():
            if row["root"] != "new":
                continue
            before, after = previous[relative], current.get(relative, {})
            if (before_filter.get(relative) != after or
                    any(before.get(field) != after.get(field) for field in ("mode", "size", "mtime_ns"))):
                raise ValueError("过滤改变了已选文件，请刷新差异后重新提交")
        for relative, key in self.directories.items():
            if key == "new" and (relative not in current or
                    not stat.S_ISDIR(current[relative]["mode"])):
                raise ValueError("过滤移除了已选目录，请刷新差异后重新提交")
        self.roots["new"] = root
        self.manifests["new"] = current


def build_plan(new_root, existing_root, items, decisions, source_manifest=None, existing_manifest=None):
    source_manifest = source_manifest if source_manifest is not None else snapshot(new_root)
    existing_manifest = existing_manifest if existing_manifest is not None else snapshot(existing_root)
    manifests = {"new": source_manifest, "old": existing_manifest}
    for manifest in manifests.values():
        if any(not (stat.S_ISDIR(row["mode"]) or stat.S_ISREG(row["mode"])) for row in manifest.values()):
            raise ValueError("合并目录包含符号链接或特殊文件，请先处理后刷新差异")
    files, directories, deleted = {}, {}, []
    for item in items:
        relative = safe_relative(str(item["relative_path"]))
        if item["type"] == "dir":
            directories[relative] = "old" if relative in existing_manifest else "new"
            continue
        choice = decisions.get(relative, "use_old" if item["status"] in {"old_only", "unchanged"} else "use_new")
        if choice == "delete":
            deleted.append(relative)
            continue
        key = "new" if choice == "use_new" else "old"
        row = manifests[key].get(relative)
        if row is None or not stat.S_ISREG(row["mode"]):
            raise ValueError("已选文件不存在或类型冲突，请刷新差异后重新提交")
        files[relative] = {"root": key, "size": row["size"]}
        for parent in PurePosixPath(relative).parents:
            if str(parent) != ".":
                directories.setdefault(str(parent), key)
    if set(files) & set(directories):
        raise ValueError("合并结果存在文件与目录同名冲突，请先处理")
    old_files = {key for key, row in existing_manifest.items() if stat.S_ISREG(row["mode"])}
    old_dirs = {key for key, row in existing_manifest.items() if key and stat.S_ISDIR(row["mode"])}
    unchanged = set(files) == old_files and set(directories) == old_dirs and all(
        row["root"] == "old" for row in files.values())
    return MergePlan({"new": new_root, "old": existing_root}, manifests, files, directories, deleted,
                     unchanged, sum(row["size"] for row in files.values()))


def populate_plan(plan, destination, progress=None, register=None):
    plan.validate()
    config = move_config()
    client = HostMoveClient(config.socket_path, config.request_timeout_seconds) if config.host_enabled and plan.files else None
    capabilities = {}
    if client:
        for key in {row["root"] for row in plan.files.values()}:
            capability = client.probe(plan.roots[key], os.path.dirname(destination))
            if capability["same_filesystem"] and "multi_source_directory_v1" not in capability.get("capabilities", []):
                raise RuntimeError("宿主执行器缺少 multi_source_directory_v1，请先更新执行器")
            capabilities[key] = capability
    clone_roots = {key: plan.roots[key] for key, value in capabilities.items() if value["same_filesystem"]}
    operation = None
    completed = processed = 0
    started = time.perf_counter()
    clone_seconds = sync_seconds = 0.0
    try:
        if clone_roots:
            operation = str(uuid.uuid4())
            if register:
                register(operation)
            client.request("begin_multi_directory", operation_id=operation, roots=clone_roots,
                           root_identities={key: plan.manifests[key][""] for key in clone_roots},
                           destination_identity=identity(destination),
                           destination=os.path.abspath(destination), mapping_version=capabilities[next(iter(clone_roots))]["mapping_version"],
                           checkpoint=_check_scope)
        for relative in sorted(plan.directories, key=lambda value: (value.count("/"), value)):
            _check_scope()
            os.mkdir(os.path.join(destination, *relative.split("/")))
        for relative, row in plan.files.items():
            _check_scope()
            key = row["root"]
            source = os.path.join(plan.roots[key], *relative.split("/"))
            target = os.path.join(destination, *relative.split("/"))
            expected = plan.manifests[key][relative]
            if identity(source) != expected:
                raise ValueError("合并来源身份已变化，请刷新差异")
            if operation and key in clone_roots:
                result = client.request("prepare_multi_member", operation_id=operation, root_id=key,
                                        source_relative=relative, target_relative=relative, source_identity=expected,
                                        checkpoint=_check_scope)
                if identity(target) != result["destination_identity"]:
                    raise RuntimeError("克隆目标身份变化，拒绝提交")
                clone_seconds += result.get("clone_seconds", 0)
                completed += row["size"]
            else:
                with open(source, "rb", buffering=0) as reader, open(target, "xb") as writer:
                    while True:
                        _check_scope()
                        chunk = reader.read(BUFFER_SIZE)
                        if not chunk:
                            break
                        writer.write(chunk)
                        completed += len(chunk)
                        if progress:
                            progress(processed, len(plan.files), completed, plan.total_bytes, relative)
                    writer.flush()
            if identity(source) != expected or os.path.getsize(target) != row["size"]:
                raise RuntimeError("合并文件在复制期间变化，拒绝提交")
            shutil.copystat(source, target, follow_symlinks=False)
            sync_started = time.perf_counter()
            with open(target, "rb+" if os.name == "nt" else "rb") as stream:
                os.fsync(stream.fileno())
            sync_seconds += time.perf_counter() - sync_started
            processed += 1
            if progress:
                progress(processed, len(plan.files), completed, plan.total_bytes, relative)
        for relative in sorted(plan.directories, key=lambda value: value.count("/"), reverse=True):
            target = os.path.join(destination, *relative.split("/"))
            source = os.path.join(plan.roots[plan.directories[relative]], *relative.split("/"))
            if os.path.isdir(source):
                shutil.copystat(source, target, follow_symlinks=False)
            fsync_directory(target)
        shutil.copystat(plan.roots["old"], destination, follow_symlinks=False)
        fsync_directory(destination)
        fsync_directory(os.path.dirname(destination))
        plan.validate()
        actual = snapshot(destination)
        if set(actual) != {""} | set(plan.files) | set(plan.directories):
            raise RuntimeError("合并结果成员校验失败")
        for relative, row in plan.files.items():
            if not stat.S_ISREG(actual[relative]["mode"]) or actual[relative]["size"] != row["size"]:
                raise RuntimeError("合并结果文件校验失败")
        if any(not stat.S_ISDIR(actual[path]["mode"]) for path in plan.directories):
            raise RuntimeError("合并结果目录类型校验失败")
        if operation:
            client.request("finish_multi_directory", operation_id=operation, checkpoint=_check_scope)
            client.request("release", operation_id=operation)
        return {"build_seconds": time.perf_counter() - started, "clone_seconds": clone_seconds,
                "sync_seconds": sync_seconds, "processed_bytes": completed, "completed_files": processed}
    except BaseException:
        if operation:
            # cancel 与成员共用宿主锁；失败时保留目录，不能与在途 ioctl 争抢清理。
            client.request("cancel", operation_id=operation)
        raise
