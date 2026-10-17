"""合集子包的独立编码探测及混合编码目录修复。"""
import os
import sys
import zipfile
from unittest.mock import AsyncMock

import pytest

from app.core.extract_service import ExtractService
from app.core.task_engine import Task, TaskType


class EncodedZipInfo(zipfile.ZipInfo):
    def __init__(self, name, encoding):
        super().__init__(name)
        self.raw_name = name.encode(encoding)
        self.name_flags = 0x800 if encoding == 'utf-8' else 0

    def _encodeFilenameFlags(self):
        return self.raw_name, self.flag_bits | self.name_flags


def create_zip(path, entries):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, encoding in entries:
            archive.writestr(EncodedZipInfo(name, encoding), b'' if name.endswith('/') else b'payload')


@pytest.fixture
def service():
    instance = ExtractService()
    # 正式实现通过类属性访问缓存，测试间必须隔离。
    previous = ExtractService._archive_encoding_cache
    ExtractService._archive_encoding_cache = {}
    yield instance
    ExtractService._archive_encoding_cache = previous


def test_gbk_names_do_not_gain_big5_kana_bonus(service, tmp_path):
    path = tmp_path / '中文.zip'
    create_zip(path, [('大家一起来翻译_台本/', 'gbk'), ('大家一起来翻译_台本/音轨1.txt', 'gbk')])
    assert service._sniff_zip_encoding(str(path)) == 'gbk'


def test_utf8_paths_disambiguate_legacy_directory_encoding(service, tmp_path):
    path = tmp_path / '混合.zip'
    create_zip(path, [
        ('大家一起来翻译_台本/正式登录/', 'gbk'),
        ('大家一起来翻译_台本/正式登录/欢迎回来.txt', 'utf-8'),
    ])
    assert service._sniff_zip_encoding(str(path)) == 'gbk'


@pytest.mark.asyncio
async def test_children_detect_encoding_independently_of_parent(service, tmp_path):
    chinese = tmp_path / 'RJ01653669.zip'
    japanese = tmp_path / 'RJ01653910.zip'
    utf8 = tmp_path / 'RJ01653911.zip'
    create_zip(chinese, [('大家一起来翻译_台本/音轨1.txt', 'gbk')])
    create_zip(japanese, [('ささやきボイス/トラック01.txt', 'cp932')])
    create_zip(utf8, [('音声/トラック.txt', 'utf-8')])
    selected = {}

    async def extract(path, *args, **kwargs):
        selected[os.path.basename(path)] = ExtractService._archive_encoding_cache.get(path)
        return True, None

    service._try_extract_nested_direct = extract
    service._repair_truncated_archive_extensions = AsyncMock(return_value={})
    task = Task(task_type=TaskType.EXTRACT, source_path=str(tmp_path))
    assert await service._extract_nested_archives(str(tmp_path), task, parent_encoding='big5') == 3
    assert selected == {chinese.name: 'gbk', japanese.name: 'cp932', utf8.name: None}


def test_repaired_directories_merge_without_losing_files(service, tmp_path):
    source = tmp_path / '错误目录'
    target = tmp_path / '正常目录'
    (source / 'mp3').mkdir(parents=True)
    (target / 'mp3').mkdir(parents=True)
    (source / 'mp3' / '旧编码.txt').write_bytes(b'legacy')
    (target / 'mp3' / '新编码.txt').write_bytes(b'utf8')
    assert service._move_repaired_filename(str(source), str(target))
    assert not source.exists()
    assert (target / 'mp3' / '旧编码.txt').read_bytes() == b'legacy'
    assert (target / 'mp3' / '新编码.txt').read_bytes() == b'utf8'


def test_repaired_directories_keep_conflicting_files(service, tmp_path):
    source = tmp_path / '错误目录'
    target = tmp_path / '正常目录'
    source.mkdir()
    target.mkdir()
    (source / '同名.txt').write_bytes(b'legacy')
    (target / '同名.txt').write_bytes(b'utf8')
    assert not service._move_repaired_filename(str(source), str(target))
    assert (source / '同名.txt').read_bytes() == b'legacy'
    assert (target / '同名.txt').read_bytes() == b'utf8'


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows 不允许 surrogateescape 文件名')
def test_raw_gbk_directory_merges_with_utf8_file_directory(service, tmp_path):
    path = tmp_path / '混合.zip'
    prefix = '大家一起来翻译_台本/正式登录'
    create_zip(path, [
        (prefix + '/', 'gbk'),
        (prefix + '/音轨.txt', 'gbk'),
        (prefix + '/欢迎回来.txt', 'utf-8'),
    ])
    output = tmp_path / '产物'
    raw_prefix = '/'.join(part.encode('gbk').decode('utf-8', 'surrogateescape') for part in prefix.split('/'))
    (output / raw_prefix).mkdir(parents=True)
    (output / raw_prefix / '音轨.txt').write_bytes(b'legacy')
    (output / prefix).mkdir(parents=True)
    (output / prefix / '欢迎回来.txt').write_bytes(b'utf8')
    assert service._repair_zip_filenames_in_place(str(path), str(output)) == 2
    assert (output / prefix / '音轨.txt').read_bytes() == b'legacy'
    assert (output / prefix / '欢迎回来.txt').read_bytes() == b'utf8'
    assert service._filename_garbled_diagnostics(str(output))['sample'] is None
