"""旧编码文件名从 ZIP 中央目录到移动事务的回归。"""
import contextlib
import errno
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.extract_service import ExtractService
from app.core import file_move_recovery, staged_file_move


@pytest.mark.parametrize("name", ["右耳左耳.wav", "ソース.wav", "①拡張文字.wav"])
def test_zip_repair_uses_selected_cp932_and_preserves_multibyte_paths(monkeypatch, name):
    service = ExtractService()
    raw = name.encode("cp932")
    original = raw.decode("utf-8", "surrogateescape")
    entry = SimpleNamespace(flag_bits=0, orig_filename=raw.decode("cp437"))
    archive = SimpleNamespace(infolist=lambda: [entry])
    monkeypatch.setattr(service, "_is_zip_like_archive", lambda _: True)
    monkeypatch.setattr(service, "_sniff_zip_encoding", lambda _: "gbk")
    monkeypatch.setitem(service._archive_encoding_cache, "sample.zip", "gbk")
    monkeypatch.setattr("app.core.extract_service.zipfile.ZipFile", lambda _: contextlib.nullcontext(archive))
    monkeypatch.setattr("app.core.extract_service.sys.getfilesystemencoding", lambda: "utf-8")
    monkeypatch.setattr("app.core.extract_service.os.walk", lambda *a, **k: [("output", [], [original])])
    move = Mock(return_value=True)
    monkeypatch.setattr(service, "_move_repaired_filename", move)
    assert service._repair_zip_filenames_in_place("sample.zip", "output", "shift_jis") == 1
    move.assert_called_once_with(os.path.join("output", original), os.path.join("output", name))


def test_move_transaction_accepts_surrogateescaped_source(tmp_path, monkeypatch):
    """Windows 用虚拟文件操作覆盖 Linux 旧编码路径进入事务的同一调用链。"""
    source = str(tmp_path / b"\x89E.wav".decode("utf-8", "surrogateescape"))
    destination = str(tmp_path / "右.wav")
    monkeypatch.setattr(staged_file_move, "_journal_root", lambda: tmp_path / "journal")
    monkeypatch.setattr(staged_file_move, "_operation_lock", lambda _: contextlib.nullcontext())
    monkeypatch.setattr(staged_file_move, "snapshot", Mock(return_value={}))
    monkeypatch.setattr(staged_file_move, "fsync_directory", Mock())
    publish = Mock()
    monkeypatch.setattr(staged_file_move, "publish_path", publish)
    staged_file_move.move_path_sync(source, destination)
    publish.assert_called_once_with(os.path.abspath(source), os.path.abspath(destination), overwrite=False)


def test_interrupted_legacy_filename_move_can_restart(tmp_path, monkeypatch):
    """恢复入口必须能找到移动入口为原始字节路径写下的准备记录。"""
    source = str(tmp_path / b"\x89E.wav".decode("utf-8", "surrogateescape"))
    destination = str(tmp_path / "右.wav")
    root = tmp_path / "journal"
    for module in (staged_file_move, file_move_recovery):
        monkeypatch.setattr(module, "_journal_root", lambda: root)
        monkeypatch.setattr(module, "snapshot", Mock(return_value={}))
        monkeypatch.setattr(module, "fsync_directory", Mock())
    monkeypatch.setattr(staged_file_move, "publish_path", Mock(side_effect=OSError(errno.EXDEV, "跨挂载")))
    monkeypatch.setattr(staged_file_move, "copy_path_exclusive_sync", Mock(side_effect=InterruptedError))
    with pytest.raises(InterruptedError):
        staged_file_move.move_path_sync(source, destination)
    assert len(file_move_recovery.records()) == 1
    assert file_move_recovery.restart_preparing(source) is None
    assert file_move_recovery.records() == []


@pytest.mark.skipif(os.name == "nt", reason="Windows 不支持创建含 surrogateescape 的磁盘路径")
def test_real_legacy_filename_is_renamed_without_losing_content(tmp_path, monkeypatch):
    source = os.fsdecode(os.fsencode(tmp_path) + b"/\x89E.wav")
    with open(source, "wb") as stream:
        stream.write(b"audio")
    target = str(tmp_path / "右.wav")
    monkeypatch.setattr(staged_file_move, "_journal_root", lambda: tmp_path / "journal")
    assert ExtractService._move_repaired_filename(source, target)
    assert not os.path.lexists(source)
    assert (tmp_path / "右.wav").read_bytes() == b"audio"
