"""压缩包分卷组识别与大小统计工具。"""

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ArchiveVolumeGroup:
    """同一压缩包的分卷集合，volumes[0] 约定为首卷/主卷。"""

    base_name: str
    volumes: List[str]
    volume_type: str

    @property
    def main_path(self) -> str:
        return self.volumes[0] if self.volumes else ""

    @property
    def main_filename(self) -> str:
        return os.path.basename(self.main_path)


def sort_archive_volumes(paths: Iterable[str]) -> List[str]:
    """把同组分卷按主卷优先、编号升序排序。"""

    def key(path: str):
        name = os.path.basename(path).lower()

        match = re.search(r"\.part(\d+)\.(rar|zip|7z|exe)$", name, re.IGNORECASE)
        if match:
            return (0, int(match.group(1)), name)

        match = re.search(r"\.part(\d+)$", name, re.IGNORECASE)
        if match:
            return (1, int(match.group(1)), name)

        match = re.search(r"\.7z\.(\d{3})$", name, re.IGNORECASE)
        if match:
            return (2, int(match.group(1)), name)

        if name.endswith(".exe"):
            return (3, 0, name)

        match = re.search(r"\.e(\d{2})$", name, re.IGNORECASE)
        if match:
            return (4, int(match.group(1)), name)

        if name.endswith(".zip"):
            return (5, 0, name)

        match = re.search(r"\.z(\d{2})$", name, re.IGNORECASE)
        if match:
            return (6, int(match.group(1)), name)

        if name.endswith(".rar"):
            return (7, 0, name)

        match = re.search(r"\.r(\d{2})$", name, re.IGNORECASE)
        if match:
            return (8, int(match.group(1)), name)

        match = re.search(r"\.zip\.(\d{3})$", name, re.IGNORECASE)
        if match:
            return (9, int(match.group(1)), name)

        match = re.search(r"\.(\d{3})$", name, re.IGNORECASE)
        if match:
            return (10, int(match.group(1)), name)

        return (99, 0, name)

    return sorted(dict.fromkeys(paths), key=key)


def detect_archive_volume_group(
    file_path: str,
    sibling_names: Optional[Sequence[str]] = None,
) -> Optional[ArchiveVolumeGroup]:
    """从任意分卷成员定位整组分卷；单文件压缩包返回 None。"""

    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    if sibling_names is None:
        try:
            siblings = os.listdir(directory)
        except OSError:
            return None
    else:
        siblings = list(sibling_names)

    # 保留目录中真实的大小写。Docker/Linux 的文件系统大小写敏感，不能靠
    # f"{base}.zip" 重新拼接路径，否则 Foo.ZIP + Foo.Z01 会漏掉主卷。
    sibling_by_casefold = {str(name).casefold(): str(name) for name in siblings}

    def existing(name: str) -> str:
        actual = sibling_by_casefold.get(str(name).casefold(), str(name))
        return os.path.join(directory, actual)

    def collect(pattern: str) -> List[str]:
        regex = re.compile(pattern, re.IGNORECASE)
        return [existing(name) for name in siblings if regex.fullmatch(name)]

    match = re.fullmatch(r"(?P<base>.+)\.part\d+\.(?:rar|zip|7z|exe)", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = collect(rf"{re.escape(base)}\.part\d+\.(?:rar|zip|7z|exe)")
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "part")

    match = re.fullmatch(r"(?P<base>.+)\.part\d+", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = collect(rf"{re.escape(base)}\.part\d+")
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "part_no_ext")

    match = re.fullmatch(r"(?P<base>.+)\.7z\.\d{3}", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = collect(rf"{re.escape(base)}\.7z\.\d{{3}}")
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "7z")

    match = re.fullmatch(r"(?P<base>.+)\.zip\.\d{3}", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = collect(rf"{re.escape(base)}\.zip\.\d{{3}}")
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "zip_numeric_remapped")

    match = re.fullmatch(r"(?P<base>.+)\.(?:zip|z\d{2})", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = []
        zip_path = existing(f"{base}.zip")
        if os.path.isfile(zip_path):
            volumes.append(zip_path)
        volumes.extend(collect(rf"{re.escape(base)}\.z\d{{2}}"))
        if len(volumes) <= 1:
            volumes.extend(collect(rf"{re.escape(base)}\.\d{{3}}"))
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "zip_z")

    match = re.fullmatch(r"(?P<base>.+)\.(?:exe|e\d{2})", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = []
        exe_path = existing(f"{base}.exe")
        if os.path.isfile(exe_path):
            volumes.append(exe_path)
        volumes.extend(collect(rf"{re.escape(base)}\.e\d{{2}}"))
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "exe_e")

    match = re.fullmatch(r"(?P<base>.+)\.(?:rar|r\d{2})", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = []
        rar_path = existing(f"{base}.rar")
        if os.path.isfile(rar_path):
            volumes.append(rar_path)
        volumes.extend(collect(rf"{re.escape(base)}\.r\d{{2}}"))
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "rar_old")

    match = re.fullmatch(r"(?P<base>.+)\.\d{3}", filename, re.IGNORECASE)
    if match:
        base = match.group("base")
        volumes = []
        zip_path = existing(f"{base}.zip")
        if os.path.isfile(zip_path):
            volumes.append(zip_path)
        volumes.extend(collect(rf"{re.escape(base)}\.\d{{3}}"))
        if len(volumes) > 1:
            return ArchiveVolumeGroup(base, sort_archive_volumes(volumes), "numeric")

    return None


def get_archive_volume_paths(file_path: str) -> List[str]:
    """返回同组分卷路径；单文件返回自身。"""

    group = detect_archive_volume_group(file_path)
    return group.volumes if group else [file_path]


def get_archive_total_size(file_path: str) -> int:
    """统计压缩包总大小，分卷包返回整组大小。"""

    total = 0
    for path in get_archive_volume_paths(file_path):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total
