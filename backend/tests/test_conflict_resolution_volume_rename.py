"""ConflictResolutionService.rename_disguised_volumes 单元测试。

仅校验"伪装多卷"路径上的纯逻辑：参数校验闸门、原子两阶段重命名、metadata 修订；
不依赖数据库 / 任务引擎，conflict 用 SimpleNamespace 模拟（service 只读取
``conflict.conflict_type / new_path / new_metadata`` 三个字段）。
"""
import asyncio
import os
from types import SimpleNamespace

import pytest

from app.core.conflict_resolution_service import ConflictResolutionService


def _make_conflict(directory: str, suspect_files):
    """构造一个含 disguised_volume_set payload 的 mock conflict 对象。"""
    return SimpleNamespace(
        id="conflict-test",
        conflict_type="分卷压缩包后缀无法识别",
        new_path=str(suspect_files[0]["path"]) if suspect_files else "",
        new_metadata={
            "disguised_volume_set": {
                "directory": directory,
                "detected_kind": "7z",
                "suspect_files": list(suspect_files),
                "suggested_renames": [],
                "confidence": "high",
            }
        },
    )


def _write_file(path: str, content: bytes = b"x" * 4096):
    """创建一个非空文件，确保 os.rename 能正常工作。"""
    with open(path, "wb") as f:
        f.write(content)


def _run(coro):
    """同步运行协程，避免每个用例都写 asyncio.run。"""
    return asyncio.run(coro)


class TestRenameDisguisedVolumes:
    @pytest.fixture
    def service(self):
        return ConflictResolutionService()

    @pytest.fixture
    def disguised_setup(self, tmp_path):
        """生成 3 个伪装分卷文件 + 一个 mock conflict。

        - ``foo.z7.001 / foo.z7.002 / foo.z7.003`` 全是 4KB 占位字节。
        - conflict.new_metadata.disguised_volume_set.suspect_files 含三个文件。
        """
        directory = str(tmp_path)
        suspect_files = []
        for idx in range(1, 4):
            name = f"foo.z7.{idx:03d}"
            path = os.path.join(directory, name)
            _write_file(path)
            suspect_files.append({
                "path": path,
                "name": name,
                "size": 4096,
                "index": idx,
            })
        conflict = _make_conflict(directory, suspect_files)
        return directory, conflict, suspect_files

    def test_happy_path_renames_all_volumes(self, service, disguised_setup):
        """正常路径：3 个 suspect → 3 个 rename，全部按预期改名 + metadata 清掉 disguised payload。"""
        directory, conflict, suspect_files = disguised_setup
        renames = [
            {
                "old": item["path"],
                "new": os.path.join(directory, f"foo.7z.{idx:03d}"),
            }
            for idx, item in enumerate(suspect_files, start=1)
        ]

        result = _run(service.rename_disguised_volumes(conflict, renames))

        # 实际文件改名生效
        for idx in range(1, 4):
            assert os.path.exists(os.path.join(directory, f"foo.7z.{idx:03d}"))
            assert not os.path.exists(os.path.join(directory, f"foo.z7.{idx:03d}"))

        # conflict 状态正确刷新
        assert conflict.new_path == os.path.normpath(
            os.path.join(directory, "foo.7z.001")
        )
        assert "disguised_volume_set" not in conflict.new_metadata
        assert "volume_rename_history" in conflict.new_metadata
        assert len(conflict.new_metadata["volume_rename_history"]) == 3

        # 返回值
        assert len(result["renamed"]) == 3
        assert result["first_volume"].endswith("foo.7z.001")

    def test_rejects_wrong_conflict_type(self, service, disguised_setup):
        """conflict_type 不是 分卷压缩包后缀无法识别 → ValueError。"""
        directory, conflict, suspect_files = disguised_setup
        conflict.conflict_type = "EXTRACT_FAILED"
        renames = [
            {"old": item["path"], "new": os.path.join(directory, f"foo.7z.{idx:03d}")}
            for idx, item in enumerate(suspect_files, start=1)
        ]
        with pytest.raises(ValueError, match="不支持手动重命名分卷"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_missing_disguised_payload(self, service, tmp_path):
        """new_metadata 里没有 disguised_volume_set → ValueError。"""
        conflict = SimpleNamespace(
            id="c",
            conflict_type="分卷压缩包后缀无法识别",
            new_path="",
            new_metadata={},
        )
        with pytest.raises(ValueError, match="缺少分卷探测信息"):
            _run(service.rename_disguised_volumes(conflict, []))

    def test_rejects_count_mismatch(self, service, disguised_setup):
        """rename 条数 ≠ suspect 数 → ValueError（防止漏掉某一卷）。"""
        directory, conflict, suspect_files = disguised_setup
        renames = [
            {"old": suspect_files[0]["path"], "new": os.path.join(directory, "foo.7z.001")},
        ]  # 只给 1 条，少 2 条
        with pytest.raises(ValueError, match="重命名条数必须等于"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_unknown_old_path(self, service, disguised_setup, tmp_path):
        """old 不在 suspect 集合里 → ValueError（防止构造请求改任意文件）。"""
        directory, conflict, suspect_files = disguised_setup
        # 创建一个非 suspect 文件
        outside = os.path.join(directory, "outsider.txt")
        _write_file(outside)
        renames = [
            {"old": outside, "new": os.path.join(directory, "foo.7z.001")},
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match="不在探测列表内"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_dot_dot_in_new_path(self, service, disguised_setup):
        """new 含 ``..`` 路径段 → ValueError（防止跳目录）。"""
        directory, conflict, suspect_files = disguised_setup
        renames = [
            {"old": suspect_files[0]["path"], "new": "../foo.7z.001"},
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match=r"不能包含 \.\."):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_relative_path_with_separator(self, service, disguised_setup):
        """相对路径含分隔符（``foo/bar.7z.001``）→ ValueError。"""
        directory, conflict, suspect_files = disguised_setup
        renames = [
            {"old": suspect_files[0]["path"], "new": "subdir/foo.7z.001"},
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match="路径分隔符"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_absolute_path_outside_directory(self, service, disguised_setup, tmp_path):
        """绝对路径但 dir 不是 disguised.directory → ValueError。"""
        directory, conflict, suspect_files = disguised_setup
        elsewhere = str(tmp_path / "elsewhere")
        os.makedirs(elsewhere, exist_ok=True)
        renames = [
            {"old": suspect_files[0]["path"], "new": os.path.join(elsewhere, "foo.7z.001")},
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match="同一目录"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_collision_with_existing_non_suspect_file(self, service, disguised_setup):
        """new 与现有非 suspect 文件冲突 → ValueError（防止覆盖别人）。"""
        directory, conflict, suspect_files = disguised_setup
        # 在目录里放一个跟某个 new 路径冲突的非 suspect 文件
        collision_path = os.path.join(directory, "foo.7z.001")
        _write_file(collision_path, b"existing")
        renames = [
            {"old": suspect_files[0]["path"], "new": collision_path},  # 冲突
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match="目标文件已存在且非分卷"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_rejects_duplicate_new_basename(self, service, disguised_setup):
        """两个 rename 指向相同 new basename → ValueError（避免最后只保留一份）。"""
        directory, conflict, suspect_files = disguised_setup
        same_target = os.path.join(directory, "foo.7z.001")
        renames = [
            {"old": suspect_files[0]["path"], "new": same_target},
            {"old": suspect_files[1]["path"], "new": same_target},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        with pytest.raises(ValueError, match="新文件名重复"):
            _run(service.rename_disguised_volumes(conflict, renames))

    def test_swap_volume_names_works_via_two_phase_rename(self, service, disguised_setup):
        """互换两个分卷名（典型边界）：两阶段方案保证 old 集合 = new 集合时也不会丢文件。"""
        directory, conflict, suspect_files = disguised_setup
        # foo.z7.001 / .002 / .003 → 改成 foo.7z.001 / .002 / .003，但故意把 1 和 2 互换
        renames = [
            {"old": suspect_files[0]["path"], "new": os.path.join(directory, "foo.7z.002")},
            {"old": suspect_files[1]["path"], "new": os.path.join(directory, "foo.7z.001")},
            {"old": suspect_files[2]["path"], "new": os.path.join(directory, "foo.7z.003")},
        ]
        _run(service.rename_disguised_volumes(conflict, renames))
        for idx in range(1, 4):
            assert os.path.exists(os.path.join(directory, f"foo.7z.{idx:03d}"))
        # 没有残留 .tmp
        for entry in os.listdir(directory):
            assert ".tmp" not in entry, f"残留 tmp 文件: {entry}"


class TestDeleteSplitSiblings:
    @pytest.fixture
    def service(self):
        return ConflictResolutionService()

    def test_delete_pure_numeric_volumes_and_empty_parent(self, service, tmp_path):
        """SKIP 删除 RJ01547012.001 时，要把 RJ01547012.002 和空目录一起清掉。"""
        source_dir = tmp_path / "RJ01547012"
        source_dir.mkdir()
        first = source_dir / "RJ01547012.001"
        second = source_dir / "RJ01547012.002"
        _write_file(str(first))
        _write_file(str(second))

        service._delete_local_file_with_split_siblings(str(first))

        assert not first.exists()
        assert not second.exists()
        assert not source_dir.exists()

    def test_delete_split_siblings_keeps_unrelated_files_and_parent(self, service, tmp_path):
        """同目录有无关文件时只删同组分卷，父目录保留。"""
        first = tmp_path / "RJ01547012.001"
        second = tmp_path / "RJ01547012.002"
        unrelated = tmp_path / "RJ01547013.002"
        marker = tmp_path / "readme.txt"
        for item in (first, second, unrelated, marker):
            _write_file(str(item))

        service._delete_local_file_with_split_siblings(str(first))

        assert not first.exists()
        assert not second.exists()
        assert unrelated.exists()
        assert marker.exists()
        assert tmp_path.exists()
