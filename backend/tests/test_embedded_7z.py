"""图片壳内嵌 7z 的识别、入队及解压链路回归。"""

import asyncio
import shutil
import struct
import subprocess
import zlib
from unittest.mock import patch

import pytest
from watchdog.events import FileCreatedEvent

from app.core.archive_detection import detect_embedded_7z_offset
from app.core.extract_service import ExtractService
from app.core.file_processor import FileProcessor
from app.core.watcher import ArchiveHandler


def make_header(next_offset=0, next_size=1):
    start = struct.pack('<QQI', next_offset, next_size, zlib.crc32(b'\x00'))
    return b"7z\xbc\xaf\x27\x1c\x00\x04" + struct.pack('<I', zlib.crc32(start)) + start


@pytest.mark.parametrize('offset', [1, 289470, 65531, 65535, 65536, 8 * 1024 * 1024])
def test_detect_valid_embedded_header(tmp_path, offset):
    path = tmp_path / 'image.jpg'
    path.write_bytes(b'x' * offset + make_header() + b'\x00')
    assert detect_embedded_7z_offset(str(path)) == offset


@pytest.mark.parametrize('case', ['crc', 'bounds', 'truncated', 'ordinary', 'limit', 'signature'])
def test_reject_invalid_or_nonembedded_header(tmp_path, case):
    header = make_header()
    prefix = b'\xff\xd8\xff\xe0' + b'x' * 100
    if case == 'crc':
        header = header[:8] + b'\x00' * 4 + header[12:]
    elif case == 'bounds':
        header = make_header(next_offset=10000)
    elif case == 'truncated':
        header = header[:20]
    elif case == 'ordinary':
        prefix = b''
    elif case == 'limit':
        prefix = b'x' * (8 * 1024 * 1024 + 1)
    elif case == 'signature':
        header = b"7z\xbc\xaf\x27\x1c" + b'x' * 26
    path = tmp_path / 'image.jpg'
    path.write_bytes(prefix + header + b'\x00')
    assert detect_embedded_7z_offset(str(path)) is None


def test_false_signature_does_not_hide_later_archive(tmp_path):
    prefix = b'picture' + make_header(next_offset=10000) + b'\x00'
    path = tmp_path / 'image.jpg'
    path.write_bytes(prefix + make_header() + b'\x00')
    assert detect_embedded_7z_offset(str(path)) == len(prefix)
    assert detect_embedded_7z_offset(str(tmp_path / 'missing.jpg')) is None


@pytest.fixture
def disguised_archive(tmp_path):
    executable = shutil.which('7zz') or shutil.which('7z')
    if not executable:
        pytest.skip('真实解压回归需要安装 7zz / 7z')
    payload = tmp_path / 'inner.txt'
    payload.write_text('图片壳压缩包回归', encoding='utf-8')
    archive = tmp_path / 'clean.7z'
    subprocess.run([executable, 'a', str(archive), str(payload)], check=True, capture_output=True)
    image = tmp_path / 'RJ01713620.jpg'
    prefix = b'\xff\xd8\xff\xe0' + b'\x00' * (289470 - 6) + b'\xff\xd9'
    image.write_bytes(prefix + archive.read_bytes())
    return image, executable


def test_image_shell_is_detected_and_delivered_to_watcher(disguised_archive):
    path, _ = disguised_archive
    detected = []
    handler = ArchiveHandler(detected.append, lambda: set(), lambda: False, lambda _: None)
    assert FileProcessor().is_archive(str(path)) is True
    handler.on_created(FileCreatedEvent(str(path)))
    assert detected == [str(path)]


@pytest.mark.asyncio
async def test_image_shell_normalizes_as_7z_and_really_extracts(disguised_archive, tmp_path):
    path, executable = disguised_archive
    service = ExtractService()
    with patch.object(service.config.extract, 'auto_repair_extension', True):
        assert await service._detect_real_type(str(path)) == '7z'
        assert await service.get_normalized_filename(str(path)) is None
        normalized = await service.normalize_archive_filename(str(path))
        # 改为 .7z 会让 7zz 强制按零偏移打开，必须保留媒体后缀。
        assert normalized == str(path)
        assert await service._repair_extension(normalized) == normalized
    output = tmp_path / 'output'
    result = await asyncio.to_thread(
        subprocess.run, [executable, 'x', normalized, f'-o{output}', '-y'],
        capture_output=True, check=True,
    )
    assert result.returncode == 0
    assert (output / 'inner.txt').read_text(encoding='utf-8') == '图片壳压缩包回归'


@pytest.mark.asyncio
async def test_real_image_keeps_its_type(tmp_path):
    path = tmp_path / 'cover.jpg'
    path.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100 + b'\xff\xd9')
    assert FileProcessor().is_archive(str(path)) is False
    assert await ExtractService()._detect_real_type(str(path)) == 'jpg'
