import os

from app.core.archive_volume_utils import (
    detect_archive_volume_group,
    get_archive_total_size,
    get_archive_volume_paths,
)


def _write_bytes(path, size: int) -> None:
    path.write_bytes(b"x" * size)


def test_exe_e_volume_total_size_from_main(tmp_path):
    exe = tmp_path / "RJ01629292.exe"
    e01 = tmp_path / "RJ01629292.e01"
    e02 = tmp_path / "RJ01629292.e02"
    _write_bytes(exe, 700)
    _write_bytes(e01, 701)
    _write_bytes(e02, 123)

    group = detect_archive_volume_group(str(exe))

    assert group is not None
    assert group.main_filename == "RJ01629292.exe"
    assert [os.path.basename(path) for path in group.volumes] == [
        "RJ01629292.exe",
        "RJ01629292.e01",
        "RJ01629292.e02",
    ]
    assert get_archive_total_size(str(exe)) == 1524


def test_exe_e_volume_total_size_from_member(tmp_path):
    exe = tmp_path / "RJ01629292.exe"
    e01 = tmp_path / "RJ01629292.e01"
    e02 = tmp_path / "RJ01629292.e02"
    _write_bytes(exe, 700)
    _write_bytes(e01, 701)
    _write_bytes(e02, 123)

    paths = get_archive_volume_paths(str(e02))

    assert [os.path.basename(path) for path in paths] == [
        "RJ01629292.exe",
        "RJ01629292.e01",
        "RJ01629292.e02",
    ]
    assert get_archive_total_size(str(e02)) == 1524


def test_zip_numeric_volume_keeps_zip_as_main(tmp_path):
    zip_path = tmp_path / "RJ00000001.zip"
    p002 = tmp_path / "RJ00000001.002"
    p003 = tmp_path / "RJ00000001.003"
    _write_bytes(zip_path, 10)
    _write_bytes(p002, 20)
    _write_bytes(p003, 30)

    group = detect_archive_volume_group(str(p003))

    assert group is not None
    assert group.main_filename == "RJ00000001.zip"
    assert get_archive_total_size(str(zip_path)) == 60


def test_single_exe_sfx_does_not_become_volume_group(tmp_path):
    exe = tmp_path / "RJ00000002.exe"
    _write_bytes(exe, 128)

    assert detect_archive_volume_group(str(exe)) is None
    assert get_archive_volume_paths(str(exe)) == [str(exe)]
    assert get_archive_total_size(str(exe)) == 128
