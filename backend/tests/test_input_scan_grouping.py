"""使用真实目录验证分卷索引不改变归组语义。"""

import os
import time

import pytest

from app.core.file_processor import FileProcessor


@pytest.mark.parametrize("suffixes", [
    [".zip", ".z01", ".z02"],
    [".zip", ".002", ".003"],
    [".rar", ".r00", ".r01"],
    [".exe", ".e01", ".e02"],
    [".7z.001", ".7z.002", ".7z.003"],
    [".part1.rar", ".part2.rar", ".part10.rar"],
    [".PART1.RAR", ".PART2.RAR", ".PART10.RAR"],
    [".part1(1234).rar", ".part2(1234).rar", ".part10(1234).rar"],
])
def test_index_preserves_groups_and_excludes_prefix_collisions(tmp_path, suffixes):
    for base in ("RJ01000001", "RJ01000001extra"):
        for suffix in suffixes:
            (tmp_path / (base + suffix)).write_bytes(b"archive")
    source = str(tmp_path / ("RJ01000001" + suffixes[0]))
    processor = FileProcessor()
    original = processor.detect_volume_set(source)
    assert original is not None
    assert len(original.volumes) == len(suffixes)
    processor._directory_members = (str(tmp_path), tuple(os.listdir(tmp_path)))
    indexed = processor.detect_volume_set(source)
    assert (indexed.type, indexed.entry_path, indexed.volumes) == (
        original.type, original.entry_path, original.volumes,
    )
    assert all("extra" not in path for path in indexed.volumes)


def test_directory_index_is_rebuilt_when_directory_changes(tmp_path):
    processor = FileProcessor()
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        files = (name + ".7z.001", name + ".7z.002")
        for file in files:
            (directory / file).write_bytes(b"archive")
        processor._directory_members = (str(directory), files)
        group = processor.detect_volume_set(str(directory / files[0]))
        assert len(group.volumes) == 2
        assert all(os.path.dirname(path) == str(directory) for path in group.volumes)


def test_hundred_groups_use_one_directory_index(tmp_path, monkeypatch):
    sources = []
    for index in range(100):
        suffixes = [".zip"] if index < 70 else [".7z.001", ".7z.002", ".7z.003"]
        for suffix in suffixes:
            path = tmp_path / (f"RJ{index:08d}" + suffix)
            path.write_bytes(b"archive")
        sources.append(str(tmp_path / (f"RJ{index:08d}" + suffixes[0])))
    processor = FileProcessor()
    processor._directory_members = (str(tmp_path), tuple(os.listdir(tmp_path)))

    def forbid_listdir(*args):
        pytest.fail("每个分卷组不得重新枚举目录")

    monkeypatch.setattr(os, "listdir", forbid_listdir)
    started = time.perf_counter()
    groups = [processor.detect_volume_set(source) for source in sources]
    elapsed = time.perf_counter() - started
    assert sum(group is not None for group in groups) == 30
    assert sum(len(group.volumes) for group in groups if group) == 90
    print(f"100组真实文件归组耗时={elapsed:.6f}s")
