"""删除前保存轻量元数据；历史树和统计只在后端生成。"""
import os
import stat

from .activity_log_lite import format_bytes_short


def local_delete_snapshot(path):
    """只读取目录项和 stat，不读取文件内容，也不跟随符号链接。"""
    items = []
    pending = [path]
    while pending:
        current = pending.pop()
        info = os.lstat(current)
        is_dir = stat.S_ISDIR(info.st_mode)
        items.append({"path": current, "type": "dir" if is_dir else "file",
                      "size": 0 if is_dir else info.st_size})
        if is_dir:
            with os.scandir(current) as entries:
                pending.extend(entry.path for entry in entries)
    return items


async def remote_delete_snapshot(client, path):
    """FileStation 分页读取元数据，串行遍历，避免对 NAS 并发递归轰炸。"""
    info = await client.stat(path)
    files = info.get("files") or []
    if not files:
        raise FileNotFoundError(path)
    pending = [(path, files[0])]
    items = []
    while pending:
        current, item = pending.pop()
        is_dir = bool(item.get("isdir"))
        size = (item.get("additional") or {}).get("size")
        if isinstance(size, dict):
            size = size.get("size")
        items.append({"path": current, "type": "dir" if is_dir else "file",
                      "size": 0 if is_dir else (int(size) if size is not None else None)})
        if not is_dir:
            continue
        offset = 0
        while True:
            response = await client.list(current, offset=offset, limit=1000)
            data = response
            children = data.get("files") or []
            if not children:
                break
            pending.extend((child["path"], child) for child in children)
            offset += len(children)
            total = data.get("total")
            if (total is not None and offset >= int(total)) or (total is None and len(children) < 1000):
                break
    return items


def delete_history_detail(results):
    """按库存和真实路径去重；失败项不计入已删除容量。"""
    entries = {}
    for result in results:
        success = result.get("success") is True
        snapshots = result.get("deleted_items") or [result]
        for item in snapshots:
            path = str(item.get("path") or result.get("path") or "").replace("\\", "/").rstrip("/")
            library_id = str(result.get("library_id") or "")
            if not path:
                continue
            key = (library_id, path)
            entry = {**item, "path": path, "library_id": library_id,
                     "success": success, "error": result.get("error") or ""}
            item_type = item.get("type") or item.get("item_type")
            entry["type"] = "dir" if item_type in {"dir", "folder"} else item_type or "unknown"
            # 父目录和子文件重复选择时，成功删除的元数据优先。
            if key not in entries or success:
                entries[key] = entry
    succeeded = [item for item in entries.values() if item["success"]]
    files = [item for item in succeeded if item.get("type") == "file"]
    folders = [item for item in succeeded if item.get("type") == "dir"]
    unknown_size_count = sum(item.get("size") is None for item in files)
    return {
        "deleted_file_count": len(files),
        "deleted_folder_count": len(folders),
        "unknown_type_count": len(succeeded) - len(files) - len(folders),
        "deleted_bytes": sum(int(item.get("size") or 0) for item in files),
        "unknown_size_count": unknown_size_count,
        "deleted_items": list(entries.values()),
    }


def delete_tree_sections(detail):
    """原样保留路径层级和库存边界，不折叠同名目录。"""
    entries = detail.get("deleted_items")
    if not isinstance(entries, list):
        entries = detail.get("results") or []
    sections = []
    for succeeded, title in ((True, "已删除"), (False, "删除失败")):
        roots, nodes = [], {}
        count = 0
        for item in entries:
            ok = item.get("success") is True and not item.get("error")
            if ok != succeeded:
                continue
            path = str(item.get("path") or "").replace("\\", "/").rstrip("/")
            if not path:
                continue
            count += 1
            library_id = str(item.get("library_id") or "")
            parts = ([library_id] if library_id else []) + [part for part in path.split("/") if part]
            parent = None
            for index, part in enumerate(parts):
                key = f"{library_id}:/{'/'.join(parts[:index + 1])}"
                if key not in nodes:
                    node = {"key": key, "label": part, "type": "dir", "children": [],
                            "variant": "deleted" if succeeded else "failed"}
                    nodes[key] = node
                    (parent["children"] if parent else roots).append(node)
                parent = nodes[key]
            if parent:
                item_type = item.get("type") or item.get("item_type")
                parent.update(type="dir" if item_type in {"dir", "folder"} else "file", error=item.get("error") or "",
                              sizeText=format_bytes_short(item.get("size")) if item.get("size") is not None else "")
        if count:
            sections.append({"key": "delete-succeeded-items" if succeeded else "delete-failed-items",
                             "title": f"{title}（{count} 项）", "rows": roots})
    return sections
