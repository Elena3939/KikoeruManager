import os
import re
from typing import Any, Dict, List, Optional


RJ_CODE_PATTERN = re.compile(r"[RVB]J(\d{8}|\d{6})(?!\d)", re.IGNORECASE)
NUMERIC_RJ_PATTERN = re.compile(r"^(\d{8}|\d{6})$")
IGNORED_SCAN_DIRS = {"__macosx", "_conflicts", "subtitles", ".git", ".svn"}


def extract_rjcode(value: str) -> Optional[str]:
    """从文本或路径片段里提取 RJ/VJ/BJ 号，兼容纯数字目录名。"""
    text = str(value or "").strip()
    if not text:
        return None

    match = RJ_CODE_PATTERN.search(text)
    if match:
        return match.group(0).upper()

    tail = os.path.basename(text.rstrip("\\/")) or text
    clean_tail = re.sub(r"^\d+\.", "", tail)
    num_match = NUMERIC_RJ_PATTERN.match(clean_tail)
    if num_match:
        return f"RJ{num_match.group(1)}"

    return None


def extract_rjcode_from_path(path: str, *, search_subfolders: bool = True, max_depth: int = 5) -> Optional[str]:
    """从路径本身或有限层级的子目录/文件名里提取 RJ 号。"""
    raw_path = str(path or "").strip()
    if not raw_path:
        return None

    direct = extract_rjcode(raw_path)
    if direct:
        return direct

    if not search_subfolders or not os.path.isdir(raw_path):
        return None

    root = os.path.abspath(raw_path)

    def walk(current: str, depth: int) -> Optional[str]:
        if depth > max_depth:
            return None
        try:
            entries = sorted(os.scandir(current), key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.lower()))
        except OSError:
            return None

        for entry in entries:
            name = entry.name
            if name.startswith(".") or name.lower() in IGNORED_SCAN_DIRS:
                continue
            found = extract_rjcode(name)
            if found:
                return found
            if entry.is_dir(follow_symlinks=False):
                nested = walk(entry.path, depth + 1)
                if nested:
                    return nested
        return None

    return walk(root, 1)


def scan_existing_folder_candidates(existing_root: str, *, max_depth: int = 4) -> List[Dict[str, Any]]:
    """扫描已有文件夹目录，返回真正可处理的 RJ 作品候选目录。

    顶层就是 RJ 目录时返回顶层；顶层是社团/合集容器时，继续向内找 RJ 目录。
    顶层目录完全找不到 RJ 时跳过，避免把社团目录当成待处理作品。
    """
    base = os.path.abspath(os.path.normpath(str(existing_root or "")))
    if not base or not os.path.isdir(base):
        return []

    candidates: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_candidate(path: str, rjcode: Optional[str], top_path: str, depth: int, source: str) -> None:
        abs_path = os.path.abspath(os.path.normpath(path))
        key = os.path.normcase(abs_path) if os.name == "nt" else abs_path
        if key in seen_paths:
            return
        seen_paths.add(key)
        candidates.append({
            "name": os.path.basename(abs_path.rstrip("\\/")) or abs_path,
            "path": abs_path,
            "rjcode": rjcode,
            "source_root": os.path.abspath(os.path.normpath(top_path)),
            "source_root_name": os.path.basename(str(top_path).rstrip("\\/")) or str(top_path),
            "relative_path": os.path.relpath(abs_path, base).replace("\\", "/"),
            "scan_depth": depth,
            "rjcode_source": source,
            "is_nested": os.path.abspath(os.path.normpath(top_path)) != abs_path,
        })

    def walk(current: str, top_path: str, depth: int) -> bool:
        folder_name = os.path.basename(current.rstrip("\\/")) or current
        rjcode = extract_rjcode(folder_name)
        if rjcode:
            add_candidate(current, rjcode, top_path, depth, "folder_name")
            return True

        if depth >= max_depth:
            return False

        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.lower())
        except OSError:
            return False

        found_child = False
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            name = entry.name
            if name.startswith(".") or name.lower() in IGNORED_SCAN_DIRS:
                continue
            if walk(entry.path, top_path, depth + 1):
                found_child = True

        return found_child

    try:
        top_entries = sorted(os.scandir(base), key=lambda entry: entry.name.lower())
    except OSError:
        return []

    for entry in top_entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name.startswith(".") or entry.name.lower() in IGNORED_SCAN_DIRS:
            continue
        walk(entry.path, entry.path, 1)

    candidates.sort(key=lambda item: str(item.get("relative_path") or "").lower())
    return candidates
