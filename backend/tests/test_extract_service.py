"""
解压服务测试
"""
import pytest
import os
import asyncio
import subprocess
import tempfile
import time
import zipfile
import struct
import binascii
from contextlib import asynccontextmanager
from unittest.mock import Mock, AsyncMock, patch

from app.core.archive_detection import detect_embedded_zip_offset
from app.core.extract_service import ArchiveInfo, ExtractService
from app.core.file_processor import FileProcessor
from app.core.task_engine import Task, TaskType

class TestExtractService:
    """测试解压服务"""
    
    @pytest.fixture
    def extract_service(self):
        """创建解压服务实例"""
        return ExtractService()
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    def create_test_zip(self, path, password=None):
        """创建测试ZIP文件"""
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('test.txt', 'test content')
            zf.writestr('test_dir/nested.txt', 'nested content')

    def test_path_too_long_error_marker(self, extract_service):
        assert extract_service._looks_like_path_too_long_error(
            "ERROR: Cannot open output file : errno=36 : File name too long : /temp/RJ/foo.mp3"
        )
        assert not extract_service._looks_like_path_too_long_error(
            "ERROR: Wrong password"
        )

    def test_single_root_path_remap_shortens_long_utf8_root(self, extract_service):
        long_root = "RJ01595857 " + ("あ" * 90)
        archive_info = ArchiveInfo(
            "RJ01595857.rar",
            [{"name": f"{long_root}/mp3/a.txt", "size": 3, "is_dir": False}],
        )

        remap = extract_service._build_single_root_path_remap(archive_info)

        assert remap == {"root_from": long_root, "root_to": "RJ01595857"}
        assert extract_service._remap_archive_relative_path(
            f"{long_root}/mp3/a.txt",
            remap,
        ) == "RJ01595857/mp3/a.txt"

    @pytest.mark.asyncio
    async def test_verify_extraction_accepts_path_remapped_root(self, extract_service, temp_dir):
        long_root = "RJ01595857 " + ("あ" * 90)
        archive_info = ArchiveInfo(
            "RJ01595857.rar",
            [{"name": f"{long_root}/mp3/a.txt", "size": 3, "is_dir": False}],
        )
        archive_info.path_remap = extract_service._build_single_root_path_remap(archive_info)
        old_verify = extract_service.config.extract.verify_after_extract
        extract_service.config.extract.verify_after_extract = True
        try:
            target_dir = os.path.join(temp_dir, "RJ01595857", "mp3")
            os.makedirs(target_dir, exist_ok=True)
            with open(os.path.join(target_dir, "a.txt"), "wb") as f:
                f.write(b"abc")

            assert await extract_service._verify_extraction(archive_info, temp_dir)
        finally:
            extract_service.config.extract.verify_after_extract = old_verify

    @pytest.mark.asyncio
    async def test_path_remap_extract_streams_to_short_root(self, extract_service, temp_dir):
        long_root = "RJ01595857 " + ("あ" * 90)
        payloads = {
            f"{long_root}/mp3/a.txt": b"abc",
            f"{long_root}/wav/b.txt": b"de",
        }
        archive_info = ArchiveInfo(
            "RJ01595857.rar",
            [
                {"name": name, "size": len(data), "is_dir": False}
                for name, data in payloads.items()
            ],
        )
        task = Mock()
        task.task_metadata = {}
        task.progress = 0
        task.is_cancelled.return_value = False
        task.wait_if_paused = AsyncMock()
        task.update_progress = Mock()

        async def fake_extract_entry(info, entry_name, target_path, password, task_arg, progress_callback=None):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            data = payloads[entry_name]
            with open(target_path, "wb") as f:
                f.write(data)
            if progress_callback:
                progress_callback(len(data))
            return True, ""

        old_verify = extract_service.config.extract.verify_after_extract
        extract_service.config.extract.verify_after_extract = True
        try:
            with patch.object(extract_service, "_extract_archive_entry_to_file", side_effect=fake_extract_entry):
                success, reason = await extract_service._try_extract_with_path_remap(
                    archive_info,
                    temp_dir,
                    "諷詠",
                    task,
                )

            assert success
            assert reason == ""
            assert archive_info.path_remap == {"root_from": long_root, "root_to": "RJ01595857"}
            assert os.path.exists(os.path.join(temp_dir, "RJ01595857", "mp3", "a.txt"))
            assert os.path.exists(os.path.join(temp_dir, "RJ01595857", "wav", "b.txt"))
            assert task.task_metadata["extract_path_remap_mode"] == "single_root_stream"
        finally:
            extract_service.config.extract.verify_after_extract = old_verify

    def create_cp932_stored_zip(self, path):
        """创建无 UTF-8 flag、文件名按 CP932 写入的最小 ZIP。"""
        entries = [
            ("mp3/2.あまあま＆意地悪姉友.mp3", b"audio-2"),
            ("mp3/3.命令引き出し色仕掛け.mp3", b"audio-3"),
            ("readme_ろまあぽ.txt", b"readme"),
        ]
        central = []
        offset = 0
        with open(path, "wb") as f:
            for name, payload in entries:
                name_bytes = name.encode("cp932")
                crc = binascii.crc32(payload) & 0xFFFFFFFF
                local = struct.pack(
                    "<IHHHHHIIIHH",
                    0x04034B50,
                    20,
                    0,
                    0,
                    0,
                    0,
                    crc,
                    len(payload),
                    len(payload),
                    len(name_bytes),
                    0,
                )
                f.write(local)
                f.write(name_bytes)
                f.write(payload)
                central.append((name_bytes, crc, len(payload), offset))
                offset += len(local) + len(name_bytes) + len(payload)
            central_start = offset
            for name_bytes, crc, size, local_offset in central:
                header = struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,
                    20,
                    20,
                    0,
                    0,
                    0,
                    0,
                    crc,
                    size,
                    size,
                    len(name_bytes),
                    0,
                    0,
                    0,
                    0,
                    0,
                    local_offset,
                )
                f.write(header)
                f.write(name_bytes)
                offset += len(header) + len(name_bytes)
            central_size = offset - central_start
            eocd = struct.pack(
                "<IHHHHIIH",
                0x06054B50,
                0,
                0,
                len(central),
                len(central),
                central_size,
                central_start,
                0,
            )
            f.write(eocd)

    def _zipcrypto_update_keys(self, keys, value):
        keys[0] = self._zipcrypto_crc32_update(keys[0], value)
        keys[1] = (keys[1] + (keys[0] & 0xFF)) & 0xFFFFFFFF
        keys[1] = (keys[1] * 134775813 + 1) & 0xFFFFFFFF
        keys[2] = self._zipcrypto_crc32_update(keys[2], (keys[1] >> 24) & 0xFF)

    @staticmethod
    def _zipcrypto_crc32_update(crc, value):
        c = (crc ^ value) & 0xFF
        for _ in range(8):
            if c & 1:
                c = (c >> 1) ^ 0xEDB88320
            else:
                c >>= 1
        return ((crc >> 8) ^ c) & 0xFFFFFFFF

    def _zipcrypto_encrypt(self, payload, password_bytes):
        keys = [0x12345678, 0x23456789, 0x34567890]
        for value in password_bytes:
            self._zipcrypto_update_keys(keys, value)
        out = bytearray()
        for plain in payload:
            temp = keys[2] | 2
            cipher = plain ^ (((temp * (temp ^ 1)) >> 8) & 0xFF)
            out.append(cipher)
            self._zipcrypto_update_keys(keys, plain)
        return bytes(out)

    def create_gbk_password_zipcrypto_zip(self, path, password):
        """创建密码字节为 GBK 的传统 ZIP 加密小包，用来复现 7zz 密码字节不兼容。"""
        name = "20260604161913.txt"
        payload = b"inner archive payload"
        self.create_gbk_password_zipcrypto_zip_with_plain_entry(path, password, name, payload)

    def create_gbk_password_zipcrypto_zip_with_plain_entry(
        self,
        path,
        password,
        encrypted_name="20260604161913.txt",
        encrypted_payload=b"inner archive payload",
        plain_name=None,
        plain_payload=b"metadata",
    ):
        """创建可选未加密小文件 + GBK 密码字节 ZipCrypto 条目的 ZIP。"""
        password_bytes = password.encode("gbk")
        crc = binascii.crc32(encrypted_payload) & 0xFFFFFFFF
        encrypt_header = bytes(range(11)) + bytes([(crc >> 24) & 0xFF])
        encrypted_data = self._zipcrypto_encrypt(encrypt_header + encrypted_payload, password_bytes)
        encrypted_name_bytes = encrypted_name.encode("ascii")
        chunks = []
        central_entries = []
        offset = 0

        if plain_name:
            plain_name_bytes = plain_name.encode("ascii")
            plain_crc = binascii.crc32(plain_payload) & 0xFFFFFFFF
            plain_local = struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                0,
                0,
                0,
                0,
                plain_crc,
                len(plain_payload),
                len(plain_payload),
                len(plain_name_bytes),
                0,
            )
            chunks.extend([plain_local, plain_name_bytes, plain_payload])
            central_entries.append((plain_name_bytes, 0, plain_crc, len(plain_payload), len(plain_payload), offset))
            offset += len(plain_local) + len(plain_name_bytes) + len(plain_payload)

        local = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0x1,
            0,
            0,
            0,
            crc,
            len(encrypted_data),
            len(encrypted_payload),
            len(encrypted_name_bytes),
            0,
        )
        chunks.extend([local, encrypted_name_bytes, encrypted_data])
        central_entries.append((encrypted_name_bytes, 0x1, crc, len(encrypted_data), len(encrypted_payload), offset))
        offset += len(local) + len(encrypted_name_bytes) + len(encrypted_data)

        central_chunks = []
        for name_bytes, flag_bits, entry_crc, compressed_size, file_size, local_offset in central_entries:
            central = struct.pack(
                "<IHHHHHHIIIHHHHHII",
                0x02014B50,
                20,
                20,
                flag_bits,
                0,
                0,
                0,
                entry_crc,
                compressed_size,
                file_size,
                len(name_bytes),
                0,
                0,
                0,
                0,
                0,
                local_offset,
            )
            central_chunks.extend([central, name_bytes])

        central_start = sum(len(chunk) for chunk in chunks)
        central_size = sum(len(chunk) for chunk in central_chunks)
        eocd = struct.pack(
            "<IHHHHIIH",
            0x06054B50,
            0,
            0,
            len(central_entries),
            len(central_entries),
            central_size,
            central_start,
            0,
        )
        with open(path, "wb") as f:
            for chunk in chunks:
                f.write(chunk)
            for chunk in central_chunks:
                f.write(chunk)
            f.write(eocd)

    def create_prefixed_zip(self, path):
        """创建前面带 MP4 壳、后面才是 ZIP 的伪装包。"""
        prefix = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00' + (b'\x00' * 128)
        with open(path, 'wb') as f:
            f.write(prefix)
        with zipfile.ZipFile(path, 'a', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('inner.txt', 'embedded zip content')
        return len(prefix)

    def create_prefixed_zip_with_prefix_size(self, path, prefix_size):
        """创建指定前缀大小的 MP4 壳 + ZIP payload。"""
        mp4_head = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00'
        prefix = mp4_head + (b'\x00' * max(0, prefix_size - len(mp4_head)))
        with open(path, 'wb') as f:
            f.write(prefix)
        with zipfile.ZipFile(path, 'a', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('inner.txt', 'embedded zip content')
        return len(prefix)
    
    @pytest.mark.asyncio
    async def test_detect_real_type_zip(self, extract_service, temp_dir):
        """测试检测ZIP文件类型"""
        zip_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(zip_path)
        
        file_type = await extract_service._detect_real_type(zip_path)
        assert file_type == 'zip'
    
    @pytest.mark.asyncio
    async def test_repair_extension(self, extract_service, temp_dir):
        """测试修复文件后缀名。

        生产代码行为：当当前后缀不在 common_archive_extensions（zip/rar/7z/...）时，
        视为"用户原始命名"，保留原 filename 再加上正确后缀（避免破坏用户意图）。
        所以 'test.zi' 会被识别为 zip 并改名为 'test.zi.zip'，而不是替换成 'test.zip'。
        """
        wrong_path = os.path.join(temp_dir, 'test.zi')
        expected_path = os.path.join(temp_dir, 'test.zi.zip')
        self.create_test_zip(wrong_path)

        result = await extract_service._repair_extension(wrong_path)

        assert result == expected_path
        assert os.path.exists(expected_path)
        assert not os.path.exists(wrong_path)

    @pytest.mark.asyncio
    async def test_repair_extension_keeps_prefixed_zip(self, extract_service, temp_dir):
        """MP4 壳 + ZIP payload 不能被修回 .mp4。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        offset = self.create_prefixed_zip(disguised_path)

        result = await extract_service._repair_extension(disguised_path)

        assert result == disguised_path
        assert detect_embedded_zip_offset(disguised_path) == offset

    @pytest.mark.asyncio
    async def test_prepare_embedded_zip_archive_materializes_clean_zip(self, extract_service, temp_dir):
        """给 7zz 用的临时视图必须从 PK 头开始，原始 source_path 不动。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Mock()
        task.task_metadata = {}
        task.update_progress = Mock()

        try:
            view_path = await extract_service._prepare_embedded_zip_archive(disguised_path, task)

            assert view_path is not None
            with open(view_path, 'rb') as f:
                assert f.read(4) == b'PK\x03\x04'
            with zipfile.ZipFile(view_path) as zf:
                assert zf.namelist() == ['inner.txt']
            assert task.task_metadata['embedded_zip_source_path'] == disguised_path
            extract_service._cleanup_embedded_zip_view(task)
            assert not os.path.exists(view_path)
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    @pytest.mark.asyncio
    async def test_prepare_embedded_zip_archive_uses_disk_io_budget(self, extract_service, temp_dir):
        """伪装 ZIP payload 复制会占用本地磁盘 IO 预算。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Mock()
        task.task_metadata = {}
        task.update_progress = Mock()
        calls = []

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        try:
            with patch("app.core.extract_service.get_resource_budget_service", return_value=Budget()):
                view_path = await extract_service._prepare_embedded_zip_archive(disguised_path, task)

            assert view_path is not None
            assert calls == [("disk_io_local", 1, "extract.embedded_zip_copy")]
            extract_service._cleanup_embedded_zip_view(task)
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    @pytest.mark.asyncio
    async def test_prepare_embedded_zip_archive_probe_only_does_not_copy_disk_io_budget(self, extract_service, temp_dir):
        """仅记录 embedded ZIP offset 时不创建临时视图，也不占用复制预算。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        task = Mock()
        task.task_metadata = {}
        task.update_progress = Mock()
        calls = []

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.extract_service.get_resource_budget_service", return_value=Budget()):
            result = await extract_service._prepare_embedded_zip_archive(disguised_path, task, materialize=False)

        assert result == disguised_path
        assert calls == []
        assert task.task_metadata["embedded_zip_source_path"] == disguised_path
        assert "embedded_zip_view_path" not in task.task_metadata

    @pytest.mark.asyncio
    async def test_prepare_embedded_zip_archive_large_prefix_materializes_immediately(self, extract_service, temp_dir):
        """大 MP4 前缀伪装 ZIP 不先交给 7zz 直啃，避免密码/list 阶段耗尽预检超时。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        offset = self.create_prefixed_zip_with_prefix_size(disguised_path, 1024)
        old_temp_path = extract_service.config.storage.temp_path
        old_threshold = extract_service.EMBEDDED_ZIP_IMMEDIATE_VIEW_MIN_PREFIX_BYTES
        extract_service.config.storage.temp_path = temp_dir
        extract_service.EMBEDDED_ZIP_IMMEDIATE_VIEW_MIN_PREFIX_BYTES = 512
        task = Mock()
        task.task_metadata = {}
        task.update_progress = Mock()

        try:
            view_path = await extract_service._prepare_embedded_zip_archive(
                disguised_path,
                task,
                materialize=False,
            )

            assert view_path is not None
            assert view_path != disguised_path
            assert task.task_metadata["embedded_zip_offset"] == offset
            assert task.task_metadata["embedded_zip_view_path"] == view_path
            with open(view_path, "rb") as f:
                assert f.read(4) == b"PK\x03\x04"
            extract_service._cleanup_embedded_zip_view(task)
        finally:
            extract_service.config.storage.temp_path = old_temp_path
            extract_service.EMBEDDED_ZIP_IMMEDIATE_VIEW_MIN_PREFIX_BYTES = old_threshold

    @pytest.mark.asyncio
    async def test_temp_dir_creation_falls_back_when_configured_temp_blocks(self, extract_service, temp_dir):
        """配置 temp 创建卡住时，应快速回退系统 temp，避免解压临时视图阻塞。"""
        calls = []
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = os.path.join(temp_dir, "slow-temp")

        def slow_mkdtemp(prefix, temp_root):
            calls.append((prefix, temp_root))
            time.sleep(2)
            return os.path.join(temp_root, prefix + "late")

        try:
            with patch("app.core.extract_service._TEMP_CREATE_TIMEOUT_SECONDS", 0.1), \
                    patch.object(extract_service, "_mkdtemp_in_root", side_effect=slow_mkdtemp), \
                    patch("app.core.extract_service.tempfile.gettempdir", return_value=temp_dir):
                view_dir = await extract_service._create_temp_dir_with_fallback(
                    "kikoerumanager_sfx_7z_view_",
                    "test",
                )

            assert view_dir == os.path.join(temp_dir, "kikoerumanager_sfx_7z_view_late")
            assert calls == [
                ("kikoerumanager_sfx_7z_view_", os.path.join(temp_dir, "slow-temp")),
                ("kikoerumanager_sfx_7z_view_", temp_dir),
            ]
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    def test_file_processor_accepts_prefixed_zip_with_mp4_suffix(self, temp_dir):
        """目录扫描 / watcher 应该把伪装成 .mp4 的 ZIP 也送进入库。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)

        assert FileProcessor().is_archive(disguised_path) is True

    def test_format_command_for_log_redacts_text_and_bytes_passwords(self, extract_service):
        """str / bytes argv 都不能把密码写入日志。"""
        cmd = [
            "7zz",
            "x",
            "-psuper_secret",
            "-oout",
            "archive.zip",
            "-p",
            "another_secret",
            b"-p\xce\xd2\xbe\xf5\xb5\xc3\xce\xd2\xca\xc7",
        ]

        redacted = extract_service._format_command_for_log(cmd)

        assert "super_secret" not in redacted
        assert "another_secret" not in redacted
        assert "\\xce\\xd2" not in redacted
        assert redacted.count("********") == 3

    def test_winzip_aes_detection_accepts_method_99(self, extract_service, temp_dir):
        archive_path = os.path.join(temp_dir, "aes-method.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("payload.bin", b"payload")

        raw = bytearray(open(archive_path, "rb").read())
        local_offset = raw.index(b"PK\x03\x04")
        central_offset = raw.index(b"PK\x01\x02")
        raw[local_offset + 8:local_offset + 10] = (99).to_bytes(2, "little")
        raw[central_offset + 10:central_offset + 12] = (99).to_bytes(2, "little")
        with open(archive_path, "wb") as fp:
            fp.write(raw)

        assert extract_service._zip_uses_winzip_aes(archive_path) is True

    @pytest.mark.asyncio
    async def test_python_zip_backend_reports_winzip_aes_as_unsupported_encryption(
        self, extract_service, temp_dir,
    ):
        archive_path = os.path.join(temp_dir, "aes.zip")
        output_path = os.path.join(temp_dir, "output")
        os.makedirs(output_path)
        with open(archive_path, "wb") as fp:
            fp.write(b"placeholder")
        extract_service._zip_uses_winzip_aes = Mock(return_value=True)
        extract_service._probe_zip_password_bytes = Mock(
            side_effect=AssertionError("WinZip AES 不应交给 Python zipfile 密码探测")
        )

        success, reason = await extract_service._try_extract_zip_with_python(
            ArchiveInfo(archive_path, []),
            output_path,
            "我觉得我是",
        )

        assert success is False
        assert reason == "unsupported_encryption"

    @pytest.mark.asyncio
    async def test_get_archive_info_plain_zip_uses_zipfile_fast_path(self, extract_service, temp_dir):
        """标准未加密 ZIP 直接读中央目录，不启动 7zz list 子进程。"""
        zip_path = os.path.join(temp_dir, 'plain.zip')
        self.create_test_zip(zip_path)
        extract_service._list_archive_contents = AsyncMock()

        archive_info = await extract_service._get_archive_info(zip_path)

        assert archive_info is not None
        assert archive_info.password == ""
        assert [item["name"] for item in archive_info.file_list] == [
            "test.txt",
            "test_dir/nested.txt",
        ]
        extract_service._list_archive_contents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_archive_info_non_utf8_zip_name_uses_zipfile_fast_path(
        self, extract_service, temp_dir,
    ):
        """非 UTF-8 flag 的非 ASCII ZIP 文件名也走 zipfile 中央目录，不回退 7zz l。"""
        zip_path = os.path.join(temp_dir, 'legacy-name.zip')
        with open(zip_path, "wb") as f:
            f.write(b"PK\x03\x04")
        raw_name = "音声.txt".encode("cp932")
        extract_service._list_archive_contents = AsyncMock()
        extract_service._sniff_zip_encoding = Mock(return_value="cp932")

        class FakeInfo:
            orig_filename = raw_name.decode("cp437")
            filename = orig_filename
            flag_bits = 0
            file_size = 1

            def is_dir(self):
                return False

        class FakeZip:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def infolist(self):
                return [FakeInfo()]

        with patch("zipfile.ZipFile", FakeZip):
            archive_info = await extract_service._get_archive_info(zip_path)

        assert archive_info is not None
        assert archive_info.file_list == [{"name": "音声.txt", "size": 1, "is_dir": False}]
        assert archive_info.detected_encoding == "cp932"
        assert ExtractService._archive_encoding_cache[str(zip_path)] == "cp932"
        extract_service._list_archive_contents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_archive_info_cp932_zip_sniffs_encoding(self, extract_service, temp_dir):
        """混合来源常见的 CP932 ZIP 应嗅探出文件名编码，避免后续校验错位。"""
        zip_path = os.path.join(temp_dir, "cp932-name.zip")
        self.create_cp932_stored_zip(zip_path)
        extract_service._list_archive_contents = AsyncMock()

        archive_info = await extract_service._get_archive_info(zip_path)

        assert archive_info is not None
        assert archive_info.detected_encoding in {"shift_jis", "cp932"}
        names = [item["name"] for item in archive_info.file_list if not item["is_dir"]]
        assert "mp3/2.あまあま＆意地悪姉友.mp3" in names
        assert "readme_ろまあぽ.txt" in names
        extract_service._list_archive_contents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_archive_wrong_password_skips_slt_and_remembers_negative_cache(
        self, extract_service, temp_dir,
    ):
        """list 阶段明确密码错误时，不再用同一密码继续跑 -slt。"""
        archive_path = os.path.join(temp_dir, 'encrypted.7z')
        with open(archive_path, 'wb') as f:
            f.write(b'7z\xbc\xaf\x27\x1c' + b'\x00' * 2048)

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"ERROR: Cannot open encrypted archive. Wrong password?",
        ))
        extract_service._run_7z_command = run_7z_command

        fingerprint = extract_service._archive_fingerprint(archive_path)
        cache_key = extract_service._password_cache_key(fingerprint, "bad-password")
        ExtractService._password_negative_cache.pop(cache_key, None)
        try:
            result = await extract_service._list_archive_contents(
                archive_path,
                password="bad-password",
            )
            assert cache_key in ExtractService._password_negative_cache
        finally:
            ExtractService._password_negative_cache.pop(cache_key, None)

        assert result is None
        assert run_7z_command.await_count == 1
        first_cmd = run_7z_command.await_args.args[0]
        assert "-ba" in first_cmd
        assert "-slt" not in first_cmd

    @pytest.mark.asyncio
    async def test_prepare_embedded_zip_archive_reuses_cached_offset(self, extract_service, temp_dir):
        """预检阶段已记录 embedded ZIP offset 时，解压准备阶段不重复探测。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        offset = self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Mock()
        task.task_metadata = {
            "embedded_zip_source_path": disguised_path,
            "embedded_zip_offset": offset,
        }
        task.update_progress = Mock()

        try:
            with patch(
                "app.core.extract_service.detect_embedded_zip_offset",
                side_effect=AssertionError("不应重复探测 offset"),
            ):
                view_path = await extract_service._prepare_embedded_zip_archive(disguised_path, task)

            assert view_path is not None
            with open(view_path, 'rb') as f:
                assert f.read(4) == b'PK\x03\x04'
            extract_service._cleanup_embedded_zip_view(task)
        finally:
            extract_service.config.storage.temp_path = old_temp_path
    
    @pytest.mark.asyncio
    async def test_detect_volume_set(self, extract_service, temp_dir):
        """测试检测分卷压缩包"""
        # 创建分卷文件
        base_path = os.path.join(temp_dir, 'test')
        for i in range(1, 4):
            with open(f"{base_path}.part{i}.rar", 'w') as f:
                f.write(f"part {i}")
        
        first_volume = f"{base_path}.part1.rar"
        volume_set = extract_service._detect_volume_set(first_volume)
        
        assert volume_set is not None
        assert len(volume_set.volumes) == 3
    
    @pytest.mark.asyncio
    async def test_detect_exe_e_sequence_volume_set(self, extract_service, temp_dir):
        """国产 SFX 工具的 .exe + .eNN 分卷组应被识别为 exe_e_sequence。"""
        base = os.path.join(temp_dir, '新建压缩')
        # 创建 .exe + .e01 + .e02
        for suffix in ('.exe', '.e01', '.e02'):
            with open(base + suffix, 'wb') as f:
                f.write(b'M' if suffix == '.exe' else b'X')

        # 从 .exe 主入口检测
        vs_from_exe = extract_service._detect_volume_set(base + '.exe')
        assert vs_from_exe is not None
        assert vs_from_exe.type == 'exe_e_sequence'
        assert len(vs_from_exe.volumes) == 3
        assert vs_from_exe.entry_path == base + '.exe'
        # 顺序：exe, e01, e02
        assert vs_from_exe.volumes[0].endswith('.exe')
        assert vs_from_exe.volumes[1].endswith('.e01')
        assert vs_from_exe.volumes[2].endswith('.e02')

        # 从 .e01 也能反查到同一个分卷组
        vs_from_e01 = extract_service._detect_volume_set(base + '.e01')
        assert vs_from_e01 is not None
        assert vs_from_e01.type == 'exe_e_sequence'

    @pytest.mark.asyncio
    async def test_detect_exe_e_sequence_requires_companion(self, extract_service, temp_dir):
        """单独的 .exe 没有 .eNN 伴随时不应被识别为分卷组。"""
        with open(os.path.join(temp_dir, 'foo.exe'), 'wb') as f:
            f.write(b'MZ')
        result = extract_service._detect_volume_set(os.path.join(temp_dir, 'foo.exe'))
        assert result is None

    @pytest.mark.asyncio
    async def test_remap_exe_e_sequence_7z_inner(self, extract_service, temp_dir):
        """7z 内嵌档：remap 应生成剥离 SFX stub 的临时 .7z.001 / .7z.002 / ... 视图。"""
        base = os.path.join(temp_dir, 'arc')
        # 在 .exe 头部塞一个 7z 魔数，让探测命中 '7z'
        sfx_prefix = b'MZ\x00\x00' + (b'\x00' * 512)
        with open(base + '.exe', 'wb') as f:
            f.write(sfx_prefix)
            f.write(b'7z\xBC\xAF\x27\x1C')
            f.write(b'\x00' * 1024)
        for suffix in ('.e01', '.e02'):
            with open(base + suffix, 'wb') as f:
                f.write(b'\x00' * 32)

        original_set = extract_service._detect_volume_set(base + '.exe')
        assert original_set is not None and original_set.type == 'exe_e_sequence'

        from unittest.mock import Mock
        task = Mock()
        task.task_metadata = {}

        new_set = await extract_service._remap_exe_e_sequence(original_set, task)
        assert new_set.type == '7z_volume_with_ext'
        assert os.path.basename(new_set.entry_path) == 'arc.7z.001'
        assert [os.path.basename(p) for p in new_set.volumes] == [
            'arc.7z.001',
            'arc.7z.002',
            'arc.7z.003',
        ]
        assert os.path.dirname(new_set.entry_path) != temp_dir

        with open(new_set.entry_path, 'rb') as f:
            assert f.read(6) == b'7z\xBC\xAF\x27\x1C'
            assert len(f.read()) == 1024

        # task_metadata 应该记录临时视图，便于失败/成功清理
        assert 'exe_e_remap' in task.task_metadata
        assert task.task_metadata['exe_e_remap']['inner_format'] == '7z'
        assert task.task_metadata['exe_e_remap']['naming'] == '7z_volume_with_ext'
        assert task.task_metadata['exe_e_remap']['mode'] == 'temporary_view'
        assert task.task_metadata['exe_e_remap']['sfx_payload_offset'] == len(sfx_prefix)

        # 原始文件不应被改名或破坏
        for suffix in ('.exe', '.e01', '.e02'):
            assert os.path.exists(base + suffix)

        await extract_service._rollback_exe_e_remap(task)
        assert not os.path.exists(os.path.dirname(new_set.entry_path))

    @pytest.mark.asyncio
    async def test_remap_exe_e_sequence_7z_inner_uses_disk_io_budget(self, extract_service, temp_dir):
        """SFX 7z 临时分卷视图的 payload 复制和伴随卷视图都占用本地磁盘 IO 预算。"""
        base = os.path.join(temp_dir, 'arc')
        sfx_prefix = b'MZ\x00\x00' + (b'\x00' * 512)
        with open(base + '.exe', 'wb') as f:
            f.write(sfx_prefix)
            f.write(b'7z\xBC\xAF\x27\x1C')
            f.write(b'\x00' * 64)
        for suffix in ('.e01', '.e02'):
            with open(base + suffix, 'wb') as f:
                f.write(b'\x00' * 32)

        original_set = extract_service._detect_volume_set(base + '.exe')
        assert original_set is not None and original_set.type == 'exe_e_sequence'

        task = Mock()
        task.task_metadata = {}
        calls = []

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.extract_service.get_resource_budget_service", return_value=Budget()):
            new_set = await extract_service._remap_exe_e_sequence(original_set, task)

        assert new_set.type == '7z_volume_with_ext'
        assert calls == [
            ("disk_io_local", 1, "extract.sfx_payload_copy"),
            ("disk_io_local", 1, "extract.sfx_volume_view"),
            ("disk_io_local", 1, "extract.sfx_volume_view"),
        ]

        await extract_service._rollback_exe_e_remap(task)

    @pytest.mark.asyncio
    async def test_remap_exe_e_sequence_zip_inner_uses_zip_split_view(self, extract_service, temp_dir):
        """ZIP-SFX 内嵌档应生成 .z01/.z02/.../.zip 临时视图。"""
        base = os.path.join(temp_dir, 'zip_sfx')
        sfx_prefix = b'MZ\x00\x00' + (b'\x00' * 512)
        local_header = (
            b'PK\x03\x04'
            + b'\x14\x00'
            + b'\x00\x00'
            + b'\x08\x00'
            + b'\x00\x00\x00\x00'
            + b'\x00\x00\x00\x00'
            + b'\x00\x00\x00\x00'
            + b'\x00\x00\x00\x00'
            + b'\x08\x00'
            + b'\x00\x00'
            + b'test.txt'
        )
        with open(base + '.exe', 'wb') as f:
            f.write(sfx_prefix)
            f.write(local_header)
            f.write(b'payload')
        for suffix, payload in (
            ('.e01', b'next-volume-1'),
            ('.e02', b'central-directory-volume'),
        ):
            with open(base + suffix, 'wb') as f:
                f.write(payload)

        original_set = extract_service._detect_volume_set(base + '.exe')
        assert original_set is not None and original_set.type == 'exe_e_sequence'

        task = Mock()
        task.task_metadata = {}

        new_set = await extract_service._remap_exe_e_sequence(original_set, task)

        assert new_set.type == 'zip_volume_main'
        assert os.path.basename(new_set.entry_path) == 'zip_sfx.zip'
        assert [os.path.basename(p) for p in new_set.volumes] == [
            'zip_sfx.z01',
            'zip_sfx.z02',
            'zip_sfx.zip',
        ]
        assert task.task_metadata['exe_e_remap']['inner_format'] == 'zip'
        assert task.task_metadata['exe_e_remap']['naming'] == 'zip_volume_main'
        assert task.task_metadata['exe_e_remap']['sfx_payload_offset'] == len(sfx_prefix)
        assert os.path.exists(base + '.exe')
        assert os.path.exists(base + '.e01')
        assert os.path.exists(base + '.e02')
        with open(new_set.volumes[0], 'rb') as f:
            assert f.read(len(sfx_prefix)) == sfx_prefix
        with open(new_set.entry_path, 'rb') as f:
            assert f.read() == b'central-directory-volume'

        await extract_service._rollback_exe_e_remap(task)
        assert not os.path.exists(os.path.dirname(new_set.entry_path))

    @pytest.mark.asyncio
    async def test_remap_exe_e_sequence_unknown_inner_uses_temporary_view(self, extract_service, temp_dir):
        """探测不到内嵌魔数时也不能物理改名 .exe/.eNN，避免复现 1.6.13 的 Headers Error 路线。"""
        base = os.path.join(temp_dir, 'unknown_sfx')
        with open(base + '.exe', 'wb') as f:
            f.write(b'MZ' + b'\x00' * 1024)
        with open(base + '.e01', 'wb') as f:
            f.write(b'next-volume')

        original_set = extract_service._detect_volume_set(base + '.exe')
        assert original_set is not None and original_set.type == 'exe_e_sequence'

        task = Mock()
        task.task_metadata = {}

        new_set = await extract_service._remap_exe_e_sequence(original_set, task)

        assert new_set.type == '7z_volume_with_ext'
        assert [os.path.basename(p) for p in new_set.volumes] == [
            'unknown_sfx.7z.001',
            'unknown_sfx.7z.002',
        ]
        assert os.path.dirname(new_set.entry_path) != temp_dir
        assert task.task_metadata['exe_e_remap']['inner_format'] == 'unknown'
        assert task.task_metadata['exe_e_remap']['mode'] == 'temporary_view'
        assert os.path.exists(base + '.exe')
        assert os.path.exists(base + '.e01')

        await extract_service._rollback_exe_e_remap(task)
        assert not os.path.exists(os.path.dirname(new_set.entry_path))

    def test_7z_split_volume_is_not_rar_fast_path(self, extract_service, temp_dir):
        """7z 分卷首卷不能因为内容探测误走 RAR/unar 快路径。"""
        archive_path = os.path.join(temp_dir, 'RJ01624471.7z.001')
        with open(archive_path, 'wb') as f:
            f.write(b'Rar!\x1A\x07\x01\x00')

        assert extract_service._is_rar_archive(archive_path) is False

    def test_part_no_ext_volume_is_not_rar_fast_path(self, extract_service, temp_dir):
        """无扩展 .part1/.part2 分卷不能因为 RAR 魔数误走 unar 快路径。"""
        archive_path = os.path.join(temp_dir, 'RJ01624471.part1')
        with open(archive_path, 'wb') as f:
            f.write(b'Rar!\x1A\x07\x01\x00')

        assert extract_service._is_rar_archive(archive_path) is False

    @pytest.mark.asyncio
    async def test_password_candidates_keep_original_path_after_rename(self, extract_service):
        """文件被规范化后，仍要从原始路径/父目录嗅探密码。"""
        old_enabled = extract_service.config.extract.filename_password_sniff_enabled
        old_templates = list(extract_service.config.extract.filename_password_sniff_templates or [])
        extract_service.config.extract.filename_password_sniff_enabled = True
        extract_service.config.extract.filename_password_sniff_templates = [
            "{name}({password})",
        ]

        async def fake_candidates(path):
            return [
                {
                    "entry_id": None,
                    "password": password,
                    "source": "文件名嗅探",
                    "rjcode": None,
                    "filename": os.path.basename(path),
                }
                for password in extract_service._get_filename_sniff_passwords(path)
            ]

        extract_service._get_password_candidates_for_archive = fake_candidates

        try:
            candidates = await extract_service._get_password_candidates_for_archive_paths([
                "/input/RJ01624471(20260531南+ 冒险者本体)/RJ01624471.part1",
                "/input/RJ01624471.part1",
            ])
        finally:
            extract_service.config.extract.filename_password_sniff_enabled = old_enabled
            extract_service.config.extract.filename_password_sniff_templates = old_templates

        assert [item["password"] for item in candidates] == ["20260531南+ 冒险者本体"]

    @pytest.mark.asyncio
    async def test_remap_exe_e_sequence_rar_inner(self, extract_service, temp_dir):
        """RAR 内嵌档：remap 应改名为 .part1.rar / .part2.rar / ..."""
        base = os.path.join(temp_dir, 'arc')
        with open(base + '.exe', 'wb') as f:
            f.write(b'MZ\x00\x00')
            f.write(b'\x00' * 1024)
            f.write(b'Rar!\x1A\x07\x01\x00')
            f.write(b'\x00' * 1024)
        for suffix in ('.e01',):
            with open(base + suffix, 'wb') as f:
                f.write(b'\x00' * 32)

        original_set = extract_service._detect_volume_set(base + '.exe')
        assert original_set.type == 'exe_e_sequence'

        from unittest.mock import Mock
        task = Mock()
        task.task_metadata = {}

        new_set = await extract_service._remap_exe_e_sequence(original_set, task)
        assert new_set.type == 'part'
        assert new_set.entry_path == base + '.part1.rar'
        assert new_set.volumes == [base + '.part1.rar', base + '.part2.rar']
        assert task.task_metadata['exe_e_remap']['inner_format'] == 'rar'
        assert task.task_metadata['exe_e_remap']['naming'] == 'part'

        for suffix in ('.exe', '.e01'):
            assert not os.path.exists(base + suffix)
        for suffix in ('.part1.rar', '.part2.rar'):
            assert os.path.exists(base + suffix)

    @pytest.mark.asyncio
    async def test_probe_sfx_inner_format(self, extract_service, temp_dir):
        """探测 SFX 内嵌档魔数：7z / RAR / unknown"""
        path_7z = os.path.join(temp_dir, 'a.exe')
        with open(path_7z, 'wb') as f:
            f.write(b'MZ' + b'\x00' * 200 + b'7z\xBC\xAF\x27\x1C' + b'\x00' * 100)
        assert extract_service._probe_sfx_inner_format(path_7z) == '7z'

        path_rar = os.path.join(temp_dir, 'b.exe')
        with open(path_rar, 'wb') as f:
            f.write(b'MZ' + b'\x00' * 200 + b'Rar!\x1A\x07\x01\x00' + b'\x00' * 100)
        assert extract_service._probe_sfx_inner_format(path_rar) == 'rar'

        path_unknown = os.path.join(temp_dir, 'c.exe')
        with open(path_unknown, 'wb') as f:
            f.write(b'MZ' + b'\x00' * 1000)
        assert extract_service._probe_sfx_inner_format(path_unknown) == 'unknown'

    def test_filename_garbled_guard_detects_surrogate(self, extract_service):
        """非法 UTF-8 文件名字节在 Linux 上会进入 surrogateescape，必须判定为乱码。"""
        assert extract_service._has_garbled_text("RJ00000001_\udce4\udcb8\udcad.mp3") is True

    def test_filename_garbled_guard_detects_shift_jis_as_gbk_mojibake(self, extract_service):
        """Shift-JIS 日文被 GBK 错解后会变成合法 CJK，不能因“没有替换符”放过。"""
        assert extract_service._has_garbled_text("僠儍僾僞乕1乽悇偟偺偊偪偊偪攝怣彈巕偺僆僫僯乕傪帇挳乿.mp3") is True
        assert extract_service._has_garbled_text("鍋靛伃鍋澹掓儭宀烘湷浜鎮囧仧鍋哄亰鍋鍋婂仾.wav") is True
        assert extract_service._has_garbled_text("チャプター1「推しのえちえち配信女子のオナニーを視聴」.mp3") is False

    def test_filename_garbled_guard_allows_normal_japanese_kanji_names(self, extract_service):
        """正常日文汉字名可能包含单个 marker 字，不能被误判为 mojibake。"""
        assert extract_service._has_garbled_text("温泉浜辺.wav") is False
        assert extract_service._has_garbled_text("温泉浜辺/read me.txt") is False
        assert extract_service._has_garbled_text("本編_温泉浜辺_特典.wav") is False
        assert extract_service._has_garbled_text("探偵の依頼.txt") is False
        assert extract_service._has_garbled_text("鎮魂歌.flac") is False
        assert extract_service._has_garbled_text("横浜デート.wav") is False
        assert extract_service._repair_mojibake_filename("温泉浜辺.wav") is None
        assert extract_service._repair_mojibake_filename("本編_温泉浜辺_特典.wav") is None

    def test_filename_garbled_guard_allows_many_normal_japanese_kanji_names(self, extract_service, temp_dir):
        """多个正常日文汉字文件名反复出现 marker，也不能靠合并评分误判。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        for index in range(30):
            name = f"温泉浜辺_特典_{index:02d}.wav"
            with open(os.path.join(root, name), "w", encoding="utf-8") as fp:
                fp.write("ok")

        assert extract_service._find_garbled_filename_sample(root, max_names=None) is None

    def test_filename_garbled_diagnostics_do_not_use_combined_score(self, extract_service, temp_dir):
        """大量合法日文 marker 不能因为拼接成一个字符串而被整体误杀。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        for index in range(120):
            with open(os.path.join(root, f"横浜_探偵の依頼_鎮魂歌_{index:03d}.txt"), "w", encoding="utf-8") as fp:
                fp.write("ok")

        diagnostics = extract_service._filename_garbled_diagnostics(root, max_names=None)

        assert diagnostics["sample"] is None
        assert diagnostics["garbled_count"] == 0

    def test_unar_encoding_candidates_try_utf8_before_shift_jis(self, extract_service):
        """UTF-8 文件名被误按 GBK 解码时，必须先给 unar 明确 UTF-8 的机会。"""
        candidates = extract_service._unar_filename_encoding_candidates(include_auto=False)
        assert candidates[:2] == ("UTF-8", "SHIFT_JIS")
        assert "CP936" in candidates

    def test_decode_7z_stdout_prefers_utf8_after_mcp(self, extract_service):
        """-mcp 只影响 7z 读取 ZIP 文件名，7z stdout 本身仍应按 UTF-8 解码。"""
        text = "01-1　Wメスガキメイドの寝かしゅオナサポ音声　効果音あり.wav"
        decoded, encoding = extract_service._decode_7z_stdout(text.encode("utf-8"))

        assert encoding == "utf-8"
        assert decoded == text

    def test_repair_surrogateescaped_cp932_filename(self, extract_service):
        """7z 若把 CP932 原始字节落到 Linux 文件名，必须重命名为合法 UTF-8。"""
        fixed_name = "Wメスガキメイド　早期購入特典"
        bad_name = fixed_name.encode("cp932").decode("utf-8", errors="surrogateescape")

        assert extract_service._has_garbled_text(bad_name) is True
        assert extract_service._repair_mojibake_filename(bad_name) == fixed_name

    def test_repair_shift_jis_mojibake_filename_from_gbk(self, extract_service, temp_dir):
        """RAR 解出 `偵偭偪...` 这类文件名时，应能反解回原始日文名。"""
        bad_name = "偵偭偪壒惡岺朳亀悇偟偺偊偪偊偪攝怣彈巕偲僆僼僷僐.wav"
        fixed_name = extract_service._repair_mojibake_filename(bad_name)
        assert fixed_name == "にっち音声工房『推しのえちえち配信女子とオフパコ.wav"
        assert extract_service._repair_mojibake_relative_path(f"RJ01378421/{bad_name}") == f"RJ01378421/{fixed_name}"

        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        bad_dir_name = "偵偭偪壒惡岺朳亀悇偟偺偊偪偊偪攝怣彈巕"
        bad_dir = os.path.join(root, bad_dir_name)
        os.makedirs(bad_dir, exist_ok=True)
        bad_file = os.path.join(bad_dir, bad_name)
        with open(bad_file, "w", encoding="utf-8") as fp:
            fp.write("ok")

        assert extract_service._repair_mojibake_filenames_in_place(root) == 2
        assert os.path.exists(os.path.join(root, "にっち音声工房『推しのえちえち配信女子", fixed_name))

    @pytest.mark.asyncio
    async def test_reject_if_garbled_repairs_before_rejecting(self, extract_service, temp_dir):
        """乱码阻断前必须先尝试反解修复，修复成功则不能清理产物。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        bad_name = "偵偭偪壒惡岺朳亀悇偟偺偊偪偊偪攝怣彈巕偲僆僼僷僐.wav"
        fixed_name = "にっち音声工房『推しのえちえち配信女子とオフパコ.wav"
        with open(os.path.join(root, bad_name), "w", encoding="utf-8") as fp:
            fp.write("ok")

        cleaned = False

        async def cleanup():
            nonlocal cleaned
            cleaned = True

        rejected = await extract_service._reject_if_garbled_after_extract(
            os.path.join(temp_dir, "dummy.zip"),
            root,
            cleanup=cleanup,
            context="test",
        )

        assert rejected is False
        assert cleaned is False
        assert os.path.exists(os.path.join(root, fixed_name))

    @pytest.mark.asyncio
    async def test_reject_if_garbled_writes_diagnostics_metadata(self, extract_service, temp_dir):
        """最终无法修复时，任务元数据要带可视化诊断字段。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        bad_name = "bad_\ufffd_name.mp3"
        with open(os.path.join(root, bad_name), "w", encoding="utf-8") as fp:
            fp.write("ok")

        cleaned = False

        async def cleanup():
            nonlocal cleaned
            cleaned = True

        task = Task(task_type=TaskType.AUTO_PROCESS, source_path=os.path.join(temp_dir, "dummy.zip"))
        rejected = await extract_service._reject_if_garbled_after_extract(
            os.path.join(temp_dir, "dummy.zip"),
            root,
            cleanup=cleanup,
            context="test",
            task=task,
        )

        assert rejected is True
        assert cleaned is True
        assert task.task_metadata["garbled_filename_sample"] == bad_name
        assert task.task_metadata["garbled_filename_score_before"] >= 30
        assert task.task_metadata["garbled_filename_codec_pairs_tried"] >= 1
        assert task.task_metadata["garbled_filename_top_samples"][0]["name"] == bad_name

    @pytest.mark.asyncio
    async def test_verify_extraction_checks_repaired_mojibake_path_size(self, extract_service, temp_dir):
        """清单是乱码名、落盘已修名时，完整性验证仍必须比较文件大小。"""
        bad_name = "偵偭偪壒惡岺朳亀悇偟偺偊偪偊偪攝怣彈巕偲僆僼僷僐.wav"
        fixed_name = "にっち音声工房『推しのえちえち配信女子とオフパコ.wav"
        root = os.path.join(temp_dir, "output")
        target_dir = os.path.join(root, "RJ01378421")
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, fixed_name), "wb") as fp:
            fp.write(b"")

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, "dummy.rar"),
            file_list=[{
                "name": f"RJ01378421/{bad_name}",
                "size": 1234,
                "is_dir": False,
            }],
            password="RJ01378421",
        )

        assert await extract_service._verify_extraction(archive_info, root) is False

    @pytest.mark.asyncio
    async def test_verify_extraction_accepts_zip_encoding_name_mismatch_when_sizes_match(
        self, extract_service, temp_dir,
    ):
        """ZIP 文件名编码错位时，文件数和大小集合完全一致即可接受解压结果。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        actual_files = {
            "mp3/2.あまあま＆意地悪姉友.mp3": b"audio-2",
            "mp3/3.命令引き出し色仕掛け.mp3": b"audio-3",
            "readme_ろまあぽ.txt": b"readme",
        }
        for name, payload in actual_files.items():
            path = os.path.join(root, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fp:
                fp.write(payload)

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, "dummy.zip"),
            file_list=[
                {"name": "mp3/bad_name_01.mp3", "size": len(b"audio-2"), "is_dir": False},
                {"name": "mp3/bad_name_02.mp3", "size": len(b"audio-3"), "is_dir": False},
                {"name": "readme_bad.txt", "size": len(b"readme"), "is_dir": False},
            ],
            password="",
        )

        assert await extract_service._verify_extraction(archive_info, root) is True

    @pytest.mark.asyncio
    async def test_verify_extraction_accepts_archive_listed_size_equivalent_to_actual_size(
        self, extract_service, temp_dir,
    ):
        """清单大小存在格式级等价差异时，不应误判为解压不完整。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        actual_size = 5_869_256_704
        listed_size = actual_size - (1 << 32)
        tar_path = os.path.join(root, "large-stream.tar")
        with open(tar_path, "wb") as fp:
            fp.truncate(actual_size)

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, "large-stream.tar.gz"),
            file_list=[{
                "name": "large-stream.tar",
                "size": listed_size,
                "is_dir": False,
            }],
            password="",
        )

        assert extract_service._archive_listed_size_matches_actual_size(
            archive_info.path,
            listed_size,
            actual_size,
        )
        assert await extract_service._verify_extraction(archive_info, root) is True

    @pytest.mark.parametrize(
        "archive_name, listed_size, actual_size, expected",
        [
            ("large-stream.tar.gz", 1_574_289_408, 5_869_256_704, True),
            ("large-stream.tgz", 1_574_289_408, 5_869_256_704, True),
            ("large-stream.gz", 1_574_289_408, 5_869_256_704, True),
            ("large-stream.zip", 1_574_289_408, 5_869_256_704, False),
            ("large-stream.tar.gz", 1_574_289_409, 5_869_256_704, False),
            ("large-stream.tar.gz", 5_869_256_704, 5_869_256_704, True),
        ],
    )
    def test_archive_listed_size_matches_actual_size(
        self,
        extract_service,
        temp_dir,
        archive_name,
        listed_size,
        actual_size,
        expected,
    ):
        """大小等价策略只接受已知格式规则，不放宽普通压缩包错配。"""
        archive_path = os.path.join(temp_dir, archive_name)

        assert (
            extract_service._archive_listed_size_matches_actual_size(
                archive_path,
                listed_size,
                actual_size,
            )
            is expected
        )

    @pytest.mark.asyncio
    async def test_verify_extraction_accepts_zstd_7z_name_mismatch_when_sizes_match(
        self, extract_service, temp_dir,
    ):
        """7z/ZSTD SFX 清单名和落盘名编码错位时，用完整大小集合兜底确认。"""
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        actual_files = {
            "【短時間媚び媚びWオナサポ集♡】/01_mp3/01_両耳天国♡.mp3": b"audio-1",
            "【短時間媚び媚びWオナサポ集♡】/01_mp3/02_耳舐めキス♡.mp3": b"audio-22",
        }
        for name, payload in actual_files.items():
            path = os.path.join(root, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fp:
                fp.write(payload)

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, "dummy.exe"),
            file_list=[
                {"name": "���̕r�g�Ĥ��Ĥ�W���ʥ��ݼ�_��/01_mp3/01_�I�����_.mp3", "size": len(b"audio-1"), "is_dir": False},
                {"name": "���̕r�g�Ĥ��Ĥ�W���ʥ��ݼ�_��/01_mp3/02_�����ᥭ��_.mp3", "size": len(b"audio-22"), "is_dir": False},
            ],
            password="",
        )
        archive_info.method = "Delta 04F71101"

        assert await extract_service._verify_extraction(archive_info, root) is True

    def test_final_filename_guard_scans_full_tree(self, extract_service, temp_dir):
        """最终兜底不只采样前 240 项，深层坏文件名也要能短路命中。

        生产实现会把磁盘上的原始 surrogateescape 名字交给 ``_safe_diagnostic_name`` 反解，
        因此返回值是修复后（"repaired"）或仅做字面转义（"escaped"）的字符串，
        不再是原始 ``\\udcXX`` 形式。这里只断言"扫到了" + "确实命中了那条深层坏文件"，
        防止 surrogate 泄漏给前端 / 落库。
        """
        root = os.path.join(temp_dir, "output")
        os.makedirs(root, exist_ok=True)
        for index in range(260):
            with open(os.path.join(root, f"track_{index:03d}.txt"), "w", encoding="utf-8") as fp:
                fp.write("ok")

        nested = os.path.join(root, "nested")
        os.makedirs(nested, exist_ok=True)
        bad_name = "RJ00000002_\udce4\udcb8\udcad.mp3"
        with open(os.path.join(nested, bad_name), "w", encoding="utf-8") as fp:
            fp.write("bad")

        sample = extract_service._find_garbled_filename_sample(root, max_names=None)
        assert sample is not None, "深层坏文件名应被全树扫描发现"
        # 命中的就是这一条 RJ00000002 坏文件（其他 track_NNN.txt 都是干净的）
        assert sample.startswith("RJ00000002_"), f"unexpected sample: {sample!r}"
        assert sample.endswith(".mp3"), f"unexpected sample: {sample!r}"
        # 返回值已经被 _safe_diagnostic_name 处理，不会含 lone surrogate（\udcXX）
        assert "\udce4" not in sample and "\udcb8" not in sample and "\udcad" not in sample

        # 浅采样（max_names=240）不应命中：260 个干净文件已经吃完采样配额，nested 进不去
        assert extract_service._find_garbled_filename_sample(root, max_names=240) is None

    @pytest.mark.asyncio
    async def test_rollback_exe_e_remap(self, extract_service, temp_dir):
        """失败回滚：把 .7z.NNN 改回原 .exe + .eNN"""
        base = os.path.join(temp_dir, 'arc')
        # 模拟已经 remap 后的状态：仅 .7z.001 / .7z.002 存在
        for suffix in ('.7z.001', '.7z.002'):
            with open(base + suffix, 'wb') as f:
                f.write(b'data')

        from unittest.mock import Mock
        task = Mock()
        task.task_metadata = {
            'exe_e_remap': {
                'inner_format': '7z',
                'naming': '7z_volume_with_ext',
                'rename_map': [
                    {'original': base + '.exe', 'renamed': base + '.7z.001'},
                    {'original': base + '.e01', 'renamed': base + '.7z.002'},
                ],
            }
        }
        await extract_service._rollback_exe_e_remap(task)

        for suffix in ('.7z.001', '.7z.002'):
            assert not os.path.exists(base + suffix)
        for suffix in ('.exe', '.e01'):
            assert os.path.exists(base + suffix)
        # metadata 标记被清掉
        assert 'exe_e_remap' not in task.task_metadata

    @pytest.mark.asyncio
    async def test_get_archive_info(self, extract_service, temp_dir):
        """测试获取压缩包信息"""
        zip_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(zip_path)
        
        archive_info = await extract_service._get_archive_info(zip_path)
        
        assert archive_info is not None
        assert len(archive_info.file_list) == 2
        assert any(f['name'] == 'test.txt' for f in archive_info.file_list)
    
    @pytest.mark.asyncio
    async def test_verify_extraction(self, extract_service, temp_dir):
        """测试解压验证。

        原实现依赖系统 ``unzip`` 命令，Windows 默认没有这个命令导致测试一直失败；
        本身这里只是要把压缩包内容解到目录里给 ``_verify_extraction`` 校验，
        用 Python 标准库 ``zipfile.extractall`` 等价替换，跨平台稳定。
        """
        # 创建压缩包
        zip_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(zip_path)

        # 获取文件信息
        archive_info = await extract_service._get_archive_info(zip_path)

        # 用 Python 内置解压器解到 output（不依赖系统 unzip）
        output_path = os.path.join(temp_dir, 'output')
        os.makedirs(output_path, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(output_path)

        # 验证
        result = await extract_service._verify_extraction(archive_info, output_path)
        assert result is True

    @pytest.mark.asyncio
    async def test_summarize_extracted_payload_rejects_zero_byte_only_output(self, extract_service, temp_dir):
        """解压产物只有 0 字节文件时，主流程不能继续入库。"""
        output_path = os.path.join(temp_dir, 'zero-output')
        os.makedirs(output_path)
        open(os.path.join(output_path, 'empty.wav'), 'wb').close()

        summary = await extract_service._summarize_extracted_payload(output_path)

        assert summary['file_count'] == 1
        assert summary['nonempty_file_count'] == 0
        assert summary['total_bytes'] == 0

    @pytest.mark.asyncio
    async def test_summarize_extracted_payload_accepts_nonempty_output(self, extract_service, temp_dir):
        """只要存在真实字节，产物统计就应放行后续清单校验。"""
        output_path = os.path.join(temp_dir, 'nonempty-output')
        os.makedirs(output_path)
        with open(os.path.join(output_path, 'voice.wav'), 'wb') as f:
            f.write(b'RIFFdata')

        summary = await extract_service._summarize_extracted_payload(output_path)

        assert summary['file_count'] == 1
        assert summary['nonempty_file_count'] == 1
        assert summary['total_bytes'] == 8

    @pytest.mark.asyncio
    async def test_extract_prefixed_zip_materializes_before_listing(
        self, extract_service, temp_dir,
    ):
        """普通解压也必须先剥离 payload，不能把媒体壳交给 7zz。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Task(task_type=TaskType.EXTRACT, source_path=disguised_path)
        task.update_progress = Mock(wraps=task.update_progress)

        async def _instant_stable(*_args, **_kwargs):
            return None

        try:
            extract_service._ensure_7z_available = AsyncMock(return_value=True)
            extract_service._wait_file_stable = AsyncMock(side_effect=_instant_stable)
            extract_service._detect_volume_set = Mock(return_value=None)
            extract_service._maybe_raise_disguised_volume_set = Mock()
            extract_service._get_password_candidates_for_archive_paths = AsyncMock(return_value=[])

            def _archive_info_for_view(view_path, *args, **kwargs):
                return ArchiveInfo(
                    view_path,
                    [{"name": "inner.txt", "size": 20, "is_dir": False}],
                    "",
                )

            extract_service._get_archive_info = AsyncMock(side_effect=_archive_info_for_view)
            extract_service._try_extract = AsyncMock(return_value=(True, "", ""))
            extract_service._summarize_extracted_payload = AsyncMock(return_value={
                "file_count": 1,
                "nonempty_file_count": 1,
                "total_bytes": 20,
            })
            extract_service._verify_extraction = AsyncMock(return_value=True)
            extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)

            output_path = await extract_service.extract(task)

            assert output_path is not None
            assert os.path.basename(output_path).startswith("movie_")
            assert extract_service._try_extract.await_count == 1
            archive_info = extract_service._try_extract.await_args.args[0]
            assert archive_info.path != disguised_path
            assert archive_info.path.endswith('.zip')
            assert task.task_metadata.get("embedded_zip_source_path") == disguised_path
            assert "embedded_zip_view_path" in task.task_metadata
            assert not os.path.exists(task.task_metadata["embedded_zip_view_path"])
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    @pytest.mark.asyncio
    async def test_extract_prefixed_zip_subtitle_probe_materializes_before_listing(
        self, extract_service, temp_dir,
    ):
        """字幕补配预检不能先直读媒体壳，否则大包会在 list/密码探测阶段耗尽超时。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=disguised_path,
            metadata={"subtitle_probe_mode": True},
        )
        task.update_progress = Mock(wraps=task.update_progress)

        async def _instant_stable(*_args, **_kwargs):
            return None

        try:
            extract_service._ensure_7z_available = AsyncMock(return_value=True)
            extract_service._wait_file_stable = AsyncMock(side_effect=_instant_stable)
            extract_service._detect_volume_set = Mock(return_value=None)
            extract_service._maybe_raise_disguised_volume_set = Mock()
            extract_service._get_password_candidates_for_archive_paths = AsyncMock(return_value=[])
            def _archive_info_for_view(view_path, *args, **kwargs):
                return ArchiveInfo(
                    view_path,
                    [{"name": "inner.txt", "size": 20, "is_dir": False}],
                    "",
                )

            extract_service._get_archive_info = AsyncMock(side_effect=_archive_info_for_view)
            extract_service._try_extract = AsyncMock(return_value=(True, "", ""))
            extract_service._summarize_extracted_payload = AsyncMock(return_value={
                "file_count": 1,
                "nonempty_file_count": 1,
                "total_bytes": 20,
            })
            extract_service._verify_extraction = AsyncMock(return_value=True)
            extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)

            output_path = await extract_service.extract(task)

            assert output_path is not None
            assert extract_service._try_extract.await_count == 1
            archive_info = extract_service._try_extract.await_args.args[0]
            assert archive_info.path != disguised_path
            assert archive_info.path.endswith('.zip')
            assert task.task_metadata.get("embedded_zip_source_path") == disguised_path
            assert "embedded_zip_view_path" in task.task_metadata
            assert not os.path.exists(task.task_metadata["embedded_zip_view_path"])
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    @pytest.mark.asyncio
    async def test_extract_prefixed_zip_does_not_try_original_even_if_7z_would_accept_it(
        self, extract_service, temp_dir,
    ):
        """伪装 ZIP 不依赖不同平台 7zz 对前缀的兼容差异。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)
        old_temp_path = extract_service.config.storage.temp_path
        extract_service.config.storage.temp_path = temp_dir
        task = Task(task_type=TaskType.EXTRACT, source_path=disguised_path)
        task.update_progress = Mock(wraps=task.update_progress)

        try:
            extract_service._ensure_7z_available = AsyncMock(return_value=True)
            extract_service._wait_file_stable = AsyncMock(return_value=None)
            extract_service._detect_volume_set = Mock(return_value=None)
            extract_service._maybe_raise_disguised_volume_set = Mock()
            extract_service._get_password_candidates_for_archive_paths = AsyncMock(return_value=[])

            def _archive_info_for_view(view_path, *args, **kwargs):
                return ArchiveInfo(
                    view_path,
                    [{"name": "inner.txt", "size": 20, "is_dir": False}],
                    "",
                )

            extract_service._get_archive_info = AsyncMock(side_effect=_archive_info_for_view)
            extract_service._try_extract = AsyncMock(return_value=(True, "", ""))
            extract_service._summarize_extracted_payload = AsyncMock(return_value={
                "file_count": 1,
                "nonempty_file_count": 1,
                "total_bytes": 20,
            })
            extract_service._verify_extraction = AsyncMock(return_value=True)
            extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)

            output_path = await extract_service.extract(task)

            assert output_path is not None
            assert extract_service._try_extract.await_count == 1
            archive_info = extract_service._try_extract.await_args.args[0]
            assert archive_info.path != disguised_path
            assert archive_info.path.endswith('.zip')
            assert task.task_metadata.get("embedded_zip_source_path") == disguised_path
            assert "embedded_zip_view_path" in task.task_metadata
            assert not os.path.exists(task.task_metadata["embedded_zip_view_path"])
        finally:
            extract_service.config.storage.temp_path = old_temp_path

    @pytest.mark.asyncio
    async def test_extract_task(self, extract_service, temp_dir):
        """测试完整的解压任务。

        原实现两处会卡死：
        1. 用 ``Mock(spec=Task)``，但 ``Task.__init__`` 里赋值的实例属性（id /
           task_metadata / _cancelled / _pause_event 等）不在类上，Mock spec 不会
           自动给出来；``extract()`` 访问 ``task.id`` / ``task.is_cancelled()`` 时
           直接抛 ``AttributeError: Mock object has no attribute 'id'``。
        2. ``extract()`` 第一步会调用 ``_wait_file_stable``，对 < 1024 字节的小
           zip 一直 ``continue`` 直到 max_wait=1800 秒（30 分钟）才返回；测试小
           zip 永远小于 1024 字节，所以这个 case 实际是死等半小时。

        修复：用真实 ``Task`` 替代 Mock；patch 掉 ``_wait_file_stable``（测试目标
        不在那段，跳过即可）；监听 ``update_progress`` 看主流程跑完了。
        """
        zip_path = os.path.join(temp_dir, 'RJ123456.zip')
        self.create_test_zip(zip_path)

        task = Task(task_type=TaskType.EXTRACT, source_path=zip_path)

        async def _instant_stable(*_args, **_kwargs):
            return None

        with patch.object(extract_service, '_wait_file_stable', side_effect=_instant_stable), \
             patch.object(task, 'update_progress', wraps=task.update_progress) as update_progress_spy:
            output_path = await extract_service.extract(task)

            assert output_path is not None
            assert os.path.exists(output_path)
            assert update_progress_spy.called

    # ---------------------------------------------------------------
    # RAR + unar fast-path（修复群晖乱码作品 - 7zz 24.08 RAR 解析器无法配置文件名编码）
    # ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_rar_unar_fast_path_returns_unavailable_when_unar_missing(
        self, extract_service, temp_dir,
    ):
        """unar 不在 PATH 时，fast-path 应返回 unar_unavailable，让上层回退 7zz。"""
        extract_service._find_unar_executable = lambda: None

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, 'rj_jp.rar'),
            file_list=[],
        )
        task = Mock()

        success, password, reason = await extract_service._try_extract_rar_with_unar(
            archive_info,
            temp_dir,
            task,
            passwords=['pwd1', ''],
            vault_passwords=[],
            password_entry_id_map={},
            password_rjcode_map={},
            manual_retry_password_only=False,
        )

        assert success is False
        assert password is None
        assert reason == 'unar_unavailable'

    @pytest.mark.asyncio
    async def test_rar_unar_fast_path_succeeds_on_correct_password(
        self, extract_service, temp_dir,
    ):
        """unar 第二个密码命中时，fast-path 返回成功密码 + 更新 archive_info。"""
        extract_service._find_unar_executable = lambda: '/usr/bin/unar'

        call_count = {'n': 0}

        async def fake_unar_extract(archive_path, output_path, password, task=None, encoding=None):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return subprocess.CompletedProcess(
                    args=['unar'], returncode=1,
                    stdout=b'', stderr=b'Failed! (Wrong password?)',
                )
            with open(os.path.join(output_path, 'voice.wav'), 'wb') as fp:
                fp.write(b'audio')
            return subprocess.CompletedProcess(
                args=['unar'], returncode=0, stdout=b'', stderr=b'',
            )

        extract_service._try_unar_extract = fake_unar_extract
        # 避免触碰真实数据库
        extract_service._record_password_usage = AsyncMock()
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, 'rj_jp.rar'),
            file_list=[],
        )

        task = Mock()
        task.task_metadata = {}
        task.rjcode = ''
        task.is_cancelled = Mock(return_value=False)
        task.wait_if_paused = AsyncMock()
        task.update_progress = Mock()

        success, password, reason = await extract_service._try_extract_rar_with_unar(
            archive_info,
            temp_dir,
            task,
            passwords=['wrong', 'correct'],
            vault_passwords=['correct'],
            password_entry_id_map={'correct': 42},
            password_rjcode_map={'correct': 'RJ01396127'},
            manual_retry_password_only=False,
        )

        assert success is True
        assert password == 'correct'
        assert reason == ''
        assert archive_info.password == 'correct'
        assert archive_info.inferred_rjcode == 'RJ01396127'
        assert task.task_metadata['rjcode'] == 'RJ01396127'
        # vault 命中应回写一次密码使用记录
        extract_service._record_password_usage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rar_unar_fast_path_signals_unsupported_for_fallback(
        self, extract_service, temp_dir,
    ):
        """unar 不识别 RAR 变体时返回 unsupported，让上层走 7zz。"""
        extract_service._find_unar_executable = lambda: '/usr/bin/unar'

        async def fake_unar_extract(archive_path, output_path, password, task=None, encoding=None):
            return subprocess.CompletedProcess(
                args=['unar'], returncode=1, stdout=b'',
                stderr=b"unar: This file isn't a supported archive format.",
            )

        extract_service._try_unar_extract = fake_unar_extract
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, 'weird.rar'),
            file_list=[],
        )

        task = Mock()
        task.task_metadata = {}
        task.is_cancelled = Mock(return_value=False)
        task.wait_if_paused = AsyncMock()
        task.update_progress = Mock()

        success, password, reason = await extract_service._try_extract_rar_with_unar(
            archive_info,
            temp_dir,
            task,
            passwords=[''],
            vault_passwords=[],
            password_entry_id_map={},
            password_rjcode_map={},
            manual_retry_password_only=False,
        )

        assert success is False
        assert password is None
        assert reason == 'unsupported'

    @pytest.mark.asyncio
    async def test_rar_unar_rc1_rejects_zero_byte_partial_output(
        self, extract_service, temp_dir,
    ):
        """unar rc=1 只留下 0 字节文件时，不能因清单误验通过而接受。"""
        extract_service._find_unar_executable = lambda: '/usr/bin/unar'
        extract_service._detect_rar_encoding_with_lsar = AsyncMock(return_value=None)
        extract_service._verify_extraction = AsyncMock(return_value=True)

        async def fake_unar_extract(archive_path, output_path, password, task=None, encoding=None):
            os.makedirs(os.path.join(output_path, 'RJ01378421'), exist_ok=True)
            open(os.path.join(output_path, 'RJ01378421', '鍋靛伃.wav'), 'wb').close()
            return subprocess.CompletedProcess(
                args=['unar'], returncode=1, stdout=b'', stderr=b'',
            )

        extract_service._try_unar_extract = fake_unar_extract

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, 'RJ01378421.rar'),
            file_list=[{
                'name': 'RJ01378421/鍋靛伃.wav',
                'size': 1234,
                'is_dir': False,
            }],
            password='RJ01378421',
        )

        task = Mock()
        task.task_metadata = {}
        task.rjcode = 'RJ01378421'
        task.is_cancelled = Mock(return_value=False)
        task.wait_if_paused = AsyncMock()
        task.update_progress = Mock()

        success, password, reason = await extract_service._try_extract_rar_with_unar(
            archive_info,
            temp_dir,
            task,
            passwords=['RJ01378421'],
            vault_passwords=[],
            password_entry_id_map={},
            password_rjcode_map={},
            manual_retry_password_only=False,
            rj_passwords=['RJ01378421'],
        )

        assert success is False
        assert password is None
        assert reason == 'partial_output'
        extract_service._verify_extraction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rar_unar_rc0_rejects_empty_output(
        self, extract_service, temp_dir,
    ):
        """unar rc=0 但没有非空产物时，不能把空目录当成功。"""
        extract_service._find_unar_executable = lambda: '/usr/bin/unar'
        extract_service._detect_rar_encoding_with_lsar = AsyncMock(return_value=None)
        extract_service._verify_extraction = AsyncMock(return_value=True)

        async def fake_unar_extract(archive_path, output_path, password, task=None, encoding=None):
            os.makedirs(os.path.join(output_path, 'empty-dir'), exist_ok=True)
            return subprocess.CompletedProcess(
                args=['unar'], returncode=0, stdout=b'', stderr=b'',
            )

        extract_service._try_unar_extract = fake_unar_extract

        archive_info = ArchiveInfo(
            path=os.path.join(temp_dir, 'RJ01624471.rar'),
            file_list=[],
        )

        task = Mock()
        task.task_metadata = {}
        task.rjcode = 'RJ01624471'
        task.is_cancelled = Mock(return_value=False)
        task.wait_if_paused = AsyncMock()
        task.update_progress = Mock()

        success, password, reason = await extract_service._try_extract_rar_with_unar(
            archive_info,
            temp_dir,
            task,
            passwords=['20260531南+ 冒险者本体'],
            vault_passwords=[],
            password_entry_id_map={},
            password_rjcode_map={},
            manual_retry_password_only=False,
        )

        assert success is False
        assert password is None
        assert reason == 'partial_output'
        extract_service._verify_extraction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rar_password_probe_skips_magic_false_positive(self, extract_service, temp_dir):
        """RAR 错密码可能吐出垃圾流，不能让 magic/流式探测误判通过。"""
        archive_path = os.path.join(temp_dir, "rj_jp.rar")
        extract_service._pick_magic_entries = lambda file_list: [{
            "name": "RJ00000001/僠儍僾僞乕1.wav",
            "size": 1024,
            "magic_offset": 0,
            "magics": (b"RIFF",),
        }]
        extract_service._probe_by_magic = AsyncMock(return_value="ok")
        extract_service._pick_probe_entry = lambda file_list: {
            "name": "RJ00000001/僠儍僾僞乕1.wav",
            "size": 1024,
        }
        extract_service._probe_by_smallest_entry = AsyncMock(return_value="wrong_password")

        result = await extract_service._probe_password(
            archive_path,
            "wrong",
            file_list=[{"name": "RJ00000001/僠儍僾僞乕1.wav", "size": 1024}],
        )

        assert result == "wrong_password"
        extract_service._probe_by_magic.assert_not_awaited()
        extract_service._probe_by_smallest_entry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_password_probe_plain_zip_uses_central_directory_only(self, extract_service, temp_dir):
        """普通未加密 ZIP 的无密码探测只读中央目录，不启动 7zz 子进程。"""
        archive_path = os.path.join(temp_dir, "plain.zip")
        self.create_test_zip(archive_path)
        extract_service._probe_by_magic = AsyncMock(return_value="wrong_password")
        extract_service._probe_by_smallest_entry = AsyncMock(return_value="wrong_password")
        extract_service._probe_by_full_test = AsyncMock(return_value="wrong_password")

        result = await extract_service._probe_password(
            archive_path,
            "",
            file_list=[{"name": "test.txt", "size": 12, "is_dir": False}],
            allow_full_test=False,
        )

        assert result == "ok"
        extract_service._probe_by_magic.assert_not_awaited()
        extract_service._probe_by_smallest_entry.assert_not_awaited()
        extract_service._probe_by_full_test.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_command_does_not_wait_for_extract_semaphore(self, extract_service):
        """7zz l 属于清单预读，不应占用真正的解压槽。"""
        class DummyStream:
            async def read(self, _size):
                return b""

        class DummyProcess:
            stdout = DummyStream()
            stderr = DummyStream()
            returncode = 0

            async def wait(self):
                return 0

            def kill(self):
                self.returncode = -9

        ExtractService._seven_zip_semaphore = asyncio.Semaphore(1)
        ExtractService._seven_zip_semaphore_limit = 1
        await ExtractService._seven_zip_semaphore.acquire()
        ExtractService._seven_zip_inspect_semaphore = None
        ExtractService._seven_zip_inspect_semaphore_limit = None

        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=DummyProcess()),
        ) as create_proc:
            try:
                result = await extract_service._run_7z_command(
                    ["7zz", "l", "-ba", "archive.zip"],
                    command_timeout=1.0,
                )
            finally:
                ExtractService._seven_zip_semaphore.release()

        assert result.returncode == 0
        create_proc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inspect_command_slot_wait_timeout_does_not_start_process(self, extract_service):
        """清单/探测槽位被占满时，等待本身也要超时，不能卡在子进程启动前。"""
        old_semaphore = ExtractService._seven_zip_inspect_semaphore
        old_limit = ExtractService._seven_zip_inspect_semaphore_limit
        old_timeout = extract_service.INSPECT_SLOT_WAIT_TIMEOUT

        ExtractService._seven_zip_inspect_semaphore = asyncio.Semaphore(1)
        ExtractService._seven_zip_inspect_semaphore_limit = 1
        await ExtractService._seven_zip_inspect_semaphore.acquire()
        extract_service.INSPECT_SLOT_WAIT_TIMEOUT = 0.01

        try:
            with patch("asyncio.create_subprocess_exec", AsyncMock()) as create_proc:
                result = await extract_service._run_7z_command(
                    ["7zz", "l", "-ba", "archive.zip"],
                    command_timeout=10.0,
                )
        finally:
            ExtractService._seven_zip_inspect_semaphore.release()
            ExtractService._seven_zip_inspect_semaphore = old_semaphore
            ExtractService._seven_zip_inspect_semaphore_limit = old_limit
            extract_service.INSPECT_SLOT_WAIT_TIMEOUT = old_timeout

        assert result.returncode == -8
        assert "等待清单/探测槽位超时" in result.stderr.decode("utf-8", errors="ignore")
        create_proc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_password_probe_slot_wait_timeout_returns_unknown(self, extract_service, temp_dir):
        """密码探测等不到清单/探测槽位时不能无限卡在 38%。"""
        old_semaphore = ExtractService._seven_zip_inspect_semaphore
        old_limit = ExtractService._seven_zip_inspect_semaphore_limit
        old_timeout = extract_service.PROBE_SLOT_WAIT_TIMEOUT
        archive_path = os.path.join(temp_dir, "RJ00000001.zip")
        self.create_test_zip(archive_path)
        task = Mock()
        task.progress = 38
        task.update_progress = Mock()

        ExtractService._seven_zip_inspect_semaphore = asyncio.Semaphore(1)
        ExtractService._seven_zip_inspect_semaphore_limit = 1
        await ExtractService._seven_zip_inspect_semaphore.acquire()
        extract_service.PROBE_SLOT_WAIT_TIMEOUT = 0.01

        try:
            with patch("asyncio.create_subprocess_exec", AsyncMock()) as create_proc:
                result = await extract_service._probe_by_smallest_entry(
                    archive_path,
                    "pwd",
                    {"name": "test.txt", "size": 12, "is_dir": False},
                    timeout=1.0,
                    task=task,
                )
        finally:
            ExtractService._seven_zip_inspect_semaphore.release()
            ExtractService._seven_zip_inspect_semaphore = old_semaphore
            ExtractService._seven_zip_inspect_semaphore_limit = old_limit
            extract_service.PROBE_SLOT_WAIT_TIMEOUT = old_timeout

        assert result == "unknown"
        create_proc.assert_not_awaited()
        messages = [str(call.args[1]) for call in task.update_progress.call_args_list]
        assert any("等待密码探测槽位" in message for message in messages)
        assert any("等待密码探测槽位超时" in message for message in messages)

    @pytest.mark.asyncio
    async def test_run_subprocess_command_cancel_terminates_process(self, extract_service):
        """unar 等非 7z 子进程在协程取消时也必须被主动终止。"""
        started = asyncio.Event()

        class DummyProcess:
            returncode = None

            def __init__(self):
                self.terminated = False
                self.killed = False

            async def communicate(self):
                started.set()
                await asyncio.sleep(60)

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                return self.returncode

        process = DummyProcess()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            runner = asyncio.create_task(
                extract_service._run_subprocess_command(["unar", "x", "archive.rar"])
            )
            await started.wait()
            runner.cancel()

            with pytest.raises(asyncio.CancelledError):
                await runner

        assert process.terminated is True

    @pytest.mark.asyncio
    async def test_password_probe_budget_wait_timeout_releases_slot(self, extract_service, temp_dir):
        """资源预算不放行时也要释放已拿到的清单/探测槽位。"""
        old_semaphore = ExtractService._seven_zip_inspect_semaphore
        old_limit = ExtractService._seven_zip_inspect_semaphore_limit
        old_timeout = extract_service.PROBE_SLOT_WAIT_TIMEOUT
        archive_path = os.path.join(temp_dir, "RJ00000002.zip")
        self.create_test_zip(archive_path)

        class StuckBudget:
            def snapshot(self):
                return {
                    "resources": {
                        "archive_inspect": {
                            "passthrough": False,
                            "active_limit": 1,
                            "available": 0,
                        },
                    },
                }

            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                await asyncio.sleep(10)
                yield

        ExtractService._seven_zip_inspect_semaphore = asyncio.Semaphore(1)
        ExtractService._seven_zip_inspect_semaphore_limit = 1
        extract_service.PROBE_SLOT_WAIT_TIMEOUT = 0.01

        try:
            with patch("app.core.extract_service.get_resource_budget_service", return_value=StuckBudget()), \
                    patch("asyncio.create_subprocess_exec", AsyncMock()) as create_proc:
                result = await extract_service._probe_by_smallest_entry(
                    archive_path,
                    "pwd",
                    {"name": "test.txt", "size": 12, "is_dir": False},
                    timeout=1.0,
                )
                available = getattr(ExtractService._seven_zip_inspect_semaphore, "_value", None)
        finally:
            ExtractService._seven_zip_inspect_semaphore = old_semaphore
            ExtractService._seven_zip_inspect_semaphore_limit = old_limit
            extract_service.PROBE_SLOT_WAIT_TIMEOUT = old_timeout

        assert result == "unknown"
        assert available == 1
        create_proc.assert_not_awaited()

    def test_archive_file_list_garbled_sample_detects_rar_toc_mojibake(self, extract_service):
        """RAR TOC 已经乱码时，不应继续交给 7zz fallback 产出同样乱码的文件。"""
        sample = extract_service._archive_file_list_garbled_sample([
            {"name": "RJ01378421/偵偭偪壒惡岺朳/01_杮曇壒惡乮wav丒SE偁傝乯/僠儍僾僞乕1.wav"},
        ])

        assert sample is not None
        assert "僠儍僾僞乕" in sample

    @pytest.mark.parametrize(
        "data, expected",
        [
            (b"PK\x03\x04rest", True),                     # ZIP local file header
            (b"7z\xbc\xaf\x27\x1c", True),                  # 7z signature
            (b"Rar!\x1a\x07\x00", True),                    # RAR4 signature
            (b"\x89PNG\r\n\x1a\nbody", True),              # PNG header
            (b"\xff\xd8\xff\xe0", True),                    # JPEG header
            (b"%PDF-1.4", True),                             # PDF header
            (b"OggS\x00\x02", True),                        # OGG header
            (b"fLaC\x00\x00", True),                        # FLAC header
            (b"\x1f\x8b\x08\x00", True),                    # gzip header
            (b"BZh91AY", True),                              # bzip2 header
            (b"\x00" * 32, False),                           # 全零，非任何已知魔数
            (b"\x12\x34\x56\x78\x9a\xbc\xde\xf0\x11\x22", False),  # 任意 AES 风格随机字节
            (b"", False),                                     # 空字节
        ],
    )
    def test_data_matches_any_known_magic(self, extract_service, data, expected):
        """伪装兜底依赖：常见格式的合法首字节应命中，AES 随机字节不应命中。

        helper 是 classmethod，靠 ExtractService 实例调更接近运行时调用形态。
        """
        assert extract_service._data_matches_any_known_magic(data) is expected

    def test_data_matches_any_known_magic_tar_offset(self, extract_service):
        """tar 头标志在 257 偏移，需要足够长的 buffer 才能命中。"""
        tar_buf = bytearray(512)
        tar_buf[257:262] = b"ustar"
        assert extract_service._data_matches_any_known_magic(bytes(tar_buf)) is True
        # 截短到 256 字节，offset=257 越界，不应命中。
        assert extract_service._data_matches_any_known_magic(bytes(tar_buf[:256])) is False

    def test_data_matches_any_known_magic_disguised_zip_in_png(self, extract_service):
        """模拟伪装内层包：声称 .png 但实际是 zip 时，helper 仍能识别 zip 魔数。

        这是 ``_probe_by_magic`` 误判的核心修复场景：正确密码下，伪装的
        ``xxx.png`` 解出来流式拿到的是 ``PK\\x03\\x04...``，原本会被声称
        PNG 的魔数比对失败而判 wrong_password；现在 helper 命中 zip 魔数，
        ``_probe_by_magic`` 改判 unknown，让 t 探测兜底。
        """
        # 伪装文件：开头是 PK 魔数（zip）但叫 .png
        disguised_zip_bytes = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
        assert extract_service._data_matches_any_known_magic(disguised_zip_bytes) is True

        # 真错密码场景：AES 解出来的是看起来随机的字节，几乎不会命中任何魔数
        random_aes_bytes = bytes.fromhex("a3b1c4d5e6f78890aabbccddeeff0011")
        assert extract_service._data_matches_any_known_magic(random_aes_bytes) is False

    # ------------------------------------------------------------------
    # _get_manual_retry_passwords：多密码重试 + 旧单字段兼容
    # ------------------------------------------------------------------
    def _make_task_with_metadata(self, metadata):
        """构造一个最小可用的 Task 实例承载 task_metadata，用来测 manual passwords helper。"""
        task = Task(task_type=TaskType.EXTRACT, source_path="/tmp/dummy.7z")
        task.task_metadata = dict(metadata or {})
        return task

    def test_get_manual_retry_passwords_with_list(self, extract_service):
        """新接口：直接读 manual_retry_passwords list 字段。"""
        task = self._make_task_with_metadata({
            "manual_retry_passwords": ["outer_pwd", "inner_pwd"],
            "manual_retry_password_only": True,
        })
        assert extract_service._get_manual_retry_passwords(task) == ["outer_pwd", "inner_pwd"]

    def test_get_manual_retry_passwords_dedupe_and_strip(self, extract_service):
        """list 里有重复 / 空 / 前后空白 → 去重保序、过滤空、normalize 后保留首次出现。"""
        task = self._make_task_with_metadata({
            "manual_retry_passwords": ["alpha", "  beta  ", "alpha", "", "gamma"],
        })
        # normalize_password_value 会 strip 首尾空白
        assert extract_service._get_manual_retry_passwords(task) == ["alpha", "beta", "gamma"]

    def test_get_manual_retry_passwords_legacy_single_field(self, extract_service):
        """旧调用方只写 manual_retry_password 单字段：fallback 必须能拿到。"""
        task = self._make_task_with_metadata({
            "manual_retry_password": "legacy_only_pwd",
            "manual_retry_password_only": True,
        })
        assert extract_service._get_manual_retry_passwords(task) == ["legacy_only_pwd"]

    def test_get_manual_retry_passwords_list_empty_falls_back_to_single(self, extract_service):
        """list 字段存在但全是空白 → fallback 到 manual_retry_password 单字段。"""
        task = self._make_task_with_metadata({
            "manual_retry_passwords": ["", "   ", None],
            "manual_retry_password": "fallback_pwd",
        })
        assert extract_service._get_manual_retry_passwords(task) == ["fallback_pwd"]

    def test_get_manual_retry_passwords_no_metadata(self, extract_service):
        """无 metadata 或 task=None → 返回空 list（走密码库默认逻辑）。"""
        assert extract_service._get_manual_retry_passwords(None) == []
        empty_task = self._make_task_with_metadata({})
        assert extract_service._get_manual_retry_passwords(empty_task) == []

    def test_get_manual_retry_passwords_list_takes_precedence_over_single(self, extract_service):
        """同时有 list + 单字段时，list 优先；单字段如果不在 list 里，不会被自动追加。

        这是为了让"用户用新接口删掉旧密码、只保留 list 里的"成为可能：
        如果两者都生效会污染候选池。
        """
        task = self._make_task_with_metadata({
            "manual_retry_passwords": ["new_pwd_1", "new_pwd_2"],
            "manual_retry_password": "stale_legacy_pwd",
        })
        assert extract_service._get_manual_retry_passwords(task) == ["new_pwd_1", "new_pwd_2"]

    def test_filename_password_sniff_reads_parent_folder_name(self, extract_service, temp_dir):
        """子压缩包自身不带密码时，也要从外层目录名套文件名密码模板。"""
        parent_dir = os.path.join(temp_dir, "RJ01624471(20260531南＋冒険者本体)")
        os.makedirs(parent_dir, exist_ok=True)
        archive_path = os.path.join(parent_dir, "bonus.zip")

        old_templates = extract_service.config.extract.filename_password_sniff_templates
        old_enabled = extract_service.config.extract.filename_password_sniff_enabled
        try:
            extract_service.config.extract.filename_password_sniff_enabled = True
            extract_service.config.extract.filename_password_sniff_templates = ["{name}({password})"]

            assert extract_service._get_filename_sniff_passwords(archive_path) == [
                "20260531南＋冒険者本体",
            ]
        finally:
            extract_service.config.extract.filename_password_sniff_templates = old_templates
            extract_service.config.extract.filename_password_sniff_enabled = old_enabled

    def test_filename_password_sniff_reads_split_archive_name(self, extract_service, temp_dir):
        """分卷文件名 RJxxxx(password).7z.001 应嗅探括号内密码。"""
        archive_path = os.path.join(temp_dir, "RJ01618696(southplus@adark).7z.001")

        old_templates = extract_service.config.extract.filename_password_sniff_templates
        old_enabled = extract_service.config.extract.filename_password_sniff_enabled
        try:
            extract_service.config.extract.filename_password_sniff_enabled = True
            extract_service.config.extract.filename_password_sniff_templates = ["{name}({password})"]

            assert extract_service._get_filename_sniff_passwords(archive_path) == [
                "southplus@adark",
            ]
        finally:
            extract_service.config.extract.filename_password_sniff_templates = old_templates
            extract_service.config.extract.filename_password_sniff_enabled = old_enabled

    def test_normalize_filename_preserves_download_password_suffix(self, extract_service):
        """监听器规范化 RJ 文件名时不能删除下载工作台写入的密码后缀。"""
        old_templates = extract_service.config.extract.filename_password_sniff_templates
        try:
            extract_service.config.extract.filename_password_sniff_templates = ["{name}({password})"]
            assert extract_service._normalize_filename("RJ01583291(secret-pass).zip") == "RJ01583291(secret-pass)"
        finally:
            extract_service.config.extract.filename_password_sniff_templates = old_templates

    def test_extract_7z_progress_ignores_terminal_control_open(self, extract_service):
        """7z 的 Open + 退格控制序列不能当成当前文件名展示。"""
        assert extract_service._extract_7z_progress_entry_name("0% - Open\b\b\b\b\b\b --") == ""
        assert extract_service._limit_progress_step("解压中 0% - Open\b\b\b\b --") == "解压中 0% - Open --"

    @pytest.mark.asyncio
    async def test_nested_extract_tries_parent_folder_sniffed_password(
        self, extract_service, temp_dir,
    ):
        """嵌套包密码候选必须包含父目录名解析出的密码，且排在通用密码前。"""
        parent_dir = os.path.join(temp_dir, "RJ01624471(20260531南＋冒険者本体)")
        os.makedirs(parent_dir, exist_ok=True)
        archive_path = os.path.join(parent_dir, "bonus.zip")
        output_path = os.path.join(temp_dir, "out")
        os.makedirs(output_path, exist_ok=True)

        old_templates = extract_service.config.extract.filename_password_sniff_templates
        old_enabled = extract_service.config.extract.filename_password_sniff_enabled
        old_password_list = extract_service.config.extract.password_list
        try:
            extract_service.config.extract.filename_password_sniff_enabled = True
            extract_service.config.extract.filename_password_sniff_templates = ["{name}({password})"]
            extract_service.config.extract.password_list = ["default_pwd"]
            extract_service._get_password_candidates_for_archive = AsyncMock(return_value=[
                {
                    "password": "20260531南＋冒険者本体",
                    "source": "文件名嗅探",
                    "entry_id": None,
                    "rjcode": None,
                    "filename": "RJ01624471(20260531南＋冒険者本体)",
                }
            ])
            extract_service._is_rar_archive = Mock(return_value=False)
            extract_service._run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout=b"",
                stderr=b"Wrong password",
            ))

            await extract_service._try_extract_nested_direct(archive_path, output_path)

            tried_passwords = [
                next((arg[2:] for arg in call.args[0] if str(arg).startswith("-p")), "")
                for call in extract_service._run_7z_command.await_args_list
            ]
            assert tried_passwords[:3] == ["", "20260531南＋冒険者本体", "default_pwd"]
        finally:
            extract_service.config.extract.filename_password_sniff_templates = old_templates
            extract_service.config.extract.filename_password_sniff_enabled = old_enabled
            extract_service.config.extract.password_list = old_password_list

    @pytest.mark.asyncio
    async def test_nested_extract_includes_manual_retry_password(self, extract_service, temp_dir):
        """手动重试指定密码必须传递到外层解压发现的内层压缩包。"""
        archive_path = os.path.join(temp_dir, "密码：3个多月了还是0进展.rrar")
        output_path = os.path.join(temp_dir, "out")
        os.makedirs(output_path, exist_ok=True)
        task = Task(
            TaskType.EXTRACT,
            os.path.join(temp_dir, "RJ01652675.rar"),
            task_id="manual-nested-password",
            metadata={
                "manual_retry_passwords": ["3个多月了还是0进展"],
                "manual_retry_password_only": True,
            },
        )

        extract_service._get_password_candidates_for_archive = AsyncMock(return_value=[
            {"password": "vault-password"},
        ])
        extract_service._is_rar_archive = Mock(return_value=False)
        extract_service._run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"Wrong password",
        ))

        await extract_service._try_extract_nested_direct(
            archive_path,
            output_path,
            task=task,
        )

        tried_passwords = [
            next((arg[2:] for arg in call.args[0] if str(arg).startswith("-p")), "")
            for call in extract_service._run_7z_command.await_args_list
        ]
        assert tried_passwords == ["", "3个多月了还是0进展"]

    @pytest.mark.asyncio
    async def test_nested_extract_retries_unsupported_method_with_zstd_backend(
        self, extract_service, temp_dir,
    ):
        """嵌套包遇到官方 7zz 不支持的 codec 时应切到 7-Zip ZS。"""
        archive_path = os.path.join(temp_dir, "nested.7z")
        output_path = os.path.join(temp_dir, "out")
        os.makedirs(output_path, exist_ok=True)

        old_password_list = extract_service.config.extract.password_list
        try:
            extract_service.config.extract.password_list = []
            extract_service._get_password_candidates_for_archive = AsyncMock(return_value=[])
            extract_service._is_rar_archive = Mock(return_value=False)
            extract_service._ensure_7z_zstd_available = AsyncMock(return_value=True)
            extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)

            async def run_command(cmd, **_kwargs):
                if cmd[0] == "7zzs":
                    return subprocess.CompletedProcess(cmd, 0, b"", b"")
                return subprocess.CompletedProcess(cmd, 2, b"", b"ERROR: Unsupported Method")

            extract_service._run_7z_command = AsyncMock(side_effect=run_command)
            with patch.object(extract_service, "_find_7z_zstd_executable", return_value="7zzs"):
                success, password = await extract_service._try_extract_nested_direct(
                    archive_path,
                    output_path,
                )

            assert success is True
            assert password is None
            commands = [call.args[0] for call in extract_service._run_7z_command.await_args_list]
            assert [command[0] for command in commands] == [extract_service.seven_zip, "7zzs"]
        finally:
            extract_service.config.extract.password_list = old_password_list

    # ------------------------------------------------------------------
    # _try_extract：清单密码优先；没有清单密码时先无密码轻量探测
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_try_extract_uses_listed_password_before_no_password(
        self, extract_service, temp_dir,
    ):
        """清单阶段已确认的非空密码优先，正式解压前仍做轻量探测防止 list 假阳性。"""
        archive_path = os.path.join(temp_dir, "RJ00000001.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "extract-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(return_value="ok")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "test.txt", "size": 12, "is_dir": False}],
            password="sana",
        )

        success, password, reason = await extract_service._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=[{
                "password": "sana",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == "sana"
        assert reason == ""
        assert task.task_metadata["extract_verified"] is True
        extract_service._probe_password.assert_awaited_once()
        probe_args = extract_service._probe_password.await_args
        assert probe_args.args[1] == "sana"
        assert probe_args.kwargs["allow_full_test"] is False
        extract_service._cleanup_extract_attempt.assert_awaited_once_with(output_path)
        first_cmd = run_7z_command.await_args.args[0]
        assert "-psana" in first_cmd

    @pytest.mark.asyncio
    async def test_try_extract_probes_no_password_when_no_listed_password(
        self, extract_service, temp_dir,
    ):
        """没有清单确认密码时，密码库候选存在也先探测无密码，避免非加密包白试密码。"""
        archive_path = os.path.join(temp_dir, "RJ00000001-plain.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "extract-output-plain")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(return_value="ok")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "test.txt", "size": 12, "is_dir": False}],
        )

        success, password, reason = await extract_service._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=[{
                "password": "sana",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == ""
        assert reason == ""
        extract_service._probe_password.assert_awaited_once()
        probe_args = extract_service._probe_password.await_args
        assert probe_args.args[1] == ""
        assert probe_args.kwargs["allow_full_test"] is False
        first_cmd = run_7z_command.await_args.args[0]
        assert not any(str(arg).startswith("-p") for arg in first_cmd)

    @pytest.mark.asyncio
    async def test_try_extract_sfx_plain_7z_uses_no_password_from_slt(
        self, extract_service, temp_dir,
    ):
        """单体 7z SFX 清单明确未加密时，不因样本探测 unknown 跳过无密码解压。"""
        archive_path = os.path.join(temp_dir, "RJ01608067(1).exe")
        with open(archive_path, "wb") as f:
            f.write(b"MZ" + (b"\0" * 543742) + b"7z\xbc\xaf\x27\x1c")
        output_path = os.path.join(temp_dir, "extract-output-sfx")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)

        slt_output = """
Path = RJ01608067
Size = 1234
Packed Size = 1000
Attributes = A
Encrypted = -
Method = LZMA2:23
Block = 0

Path = RJ01608067/image.png
Size = 456
Packed Size = 300
Attributes = A
Encrypted = -
Method = LZMA2:23
Block = 0
""".encode("utf-8")

        async def fake_run_7z_command(cmd, *args, **kwargs):
            if "-slt" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=slt_output, stderr=b"")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        run_7z_command = AsyncMock(side_effect=fake_run_7z_command)
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_by_magic = AsyncMock(return_value="unknown")
        extract_service._probe_by_smallest_entry = AsyncMock(return_value="unknown")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "RJ01608067/image.png", "size": 456, "is_dir": False}],
        )

        success, password, reason = await extract_service._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=[{
                "password": "vault-password",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == ""
        assert reason == ""
        extract_cmds = [call.args[0] for call in run_7z_command.await_args_list if "x" in call.args[0]]
        assert len(extract_cmds) == 1
        assert not any(str(arg).startswith("-p") for arg in extract_cmds[0])

    @pytest.mark.asyncio
    async def test_try_extract_sfx_plain_7z_unsupported_method_stays_lightweight(
        self, extract_service, temp_dir, monkeypatch,
    ):
        """未加密 SFX 轻量探测遇到 Unsupported Method 时，不全量解压也不试密码库。"""
        archive_path = os.path.join(temp_dir, "RJ01644635.exe")
        with open(archive_path, "wb") as f:
            f.write(b"MZ" + (b"\0" * 4096) + b"7z\xbc\xaf\x27\x1c")
        output_path = os.path.join(temp_dir, "extract-output-sfx-unsupported")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        monkeypatch.setattr(ExtractService, "UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES", 1)
        extract_service._ensure_7z_zstd_available = AsyncMock(return_value=False)

        async def fake_run_7z_command(cmd, *args, **kwargs):
            if "x" in cmd:
                raise AssertionError("不应进入完整 7zz 解压")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        extract_service._run_7z_command = AsyncMock(side_effect=fake_run_7z_command)
        extract_service._probe_7z_no_password_status = AsyncMock(return_value="plain")
        extract_service._probe_by_magic = AsyncMock(side_effect=["ok", "unsupported_method"])
        extract_service._probe_by_smallest_entry = AsyncMock(return_value="unsupported_method")
        extract_service._cleanup_extract_attempt = AsyncMock()

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{
                    "name": "cover.jpg",
                    "size": 512,
                    "is_dir": False,
                }, {
                    "name": "voice.mp3",
                    "size": 1024,
                    "is_dir": False,
                }],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": "vault-password",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is False
        assert password is None
        assert reason == "unsupported_method"
        assert task.task_metadata["extract_failure_reason"] == "unsupported_method"
        assert extract_service._probe_by_magic.await_count == 2
        extract_service._probe_by_smallest_entry.assert_not_awaited()
        extract_service._run_7z_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_try_extract_sfx_plain_7z_unsupported_method_uses_zstd_backend(
        self, extract_service, temp_dir, monkeypatch,
    ):
        """官方 7zz 不支持 ZSTD 7z 方法时，先用 ZS 轻量探测，通过后再完整解压。"""
        archive_path = os.path.join(temp_dir, "RJ01644635.exe")
        with open(archive_path, "wb") as f:
            f.write(b"MZ" + (b"\0" * 4096) + b"7z\xbc\xaf\x27\x1c")
        output_path = os.path.join(temp_dir, "extract-output-zstd")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        monkeypatch.setattr(ExtractService, "UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES", 1)

        async def fake_run_7z_command(cmd, *args, **kwargs):
            if "x" in cmd:
                assert cmd[0] == "7zzs"
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        old_zstd_path = extract_service.config.extract.seven_zip_zstd_path
        extract_service.config.extract.seven_zip_zstd_path = "7zzs"
        extract_service._find_7z_zstd_executable = Mock(return_value="7zzs")
        extract_service._ensure_7z_zstd_available = AsyncMock(return_value=True)
        extract_service._probe_7z_no_password_status = AsyncMock(return_value="plain")
        extract_service._probe_by_magic = AsyncMock(side_effect=["unsupported_method", "ok"])
        extract_service._run_7z_command = AsyncMock(side_effect=fake_run_7z_command)
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            archive_path,
            [{
                "name": "cover.jpg",
                "size": 512,
                "is_dir": False,
            }],
        )
        archive_info.method = "Delta 04F71101"

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "vault-password",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            extract_service.config.extract.seven_zip_zstd_path = old_zstd_path

        assert success is True
        assert password == ""
        assert reason == ""
        assert task.task_metadata["extract_zstd_backend_success"] is True
        assert extract_service._probe_by_magic.await_count == 2
        zstd_probe_call = extract_service._probe_by_magic.await_args_list[1]
        assert zstd_probe_call.kwargs["seven_zip_executable"] == "7zzs"
        extract_cmds = [call.args[0] for call in extract_service._run_7z_command.await_args_list if "x" in call.args[0]]
        assert len(extract_cmds) == 1
        assert extract_cmds[0][0] == "7zzs"

    def test_parse_7z_no_password_status_from_slt(self, extract_service):
        plain_output = """
Path = plain.txt
Size = 1
Attributes = A
Encrypted = -

Path = folder
Size = 0
Attributes = D
Encrypted = -
"""
        encrypted_output = """
Path = secret.txt
Size = 1
Attributes = A
Encrypted = +
"""

        assert extract_service._parse_7z_no_password_status_from_slt(plain_output) == "plain"
        assert extract_service._parse_7z_no_password_status_from_slt(encrypted_output) == "encrypted"
        assert extract_service._parse_7z_no_password_status_from_slt("Path = a.txt\nSize = 1\n") is None

    @pytest.mark.asyncio
    async def test_try_extract_manual_retry_skips_no_password_full_extract_when_probe_unknown(
        self, extract_service, temp_dir,
    ):
        """手动指定密码重试时，无密码探测无法定性就不能完整解压大包，应直接试指定密码。"""
        archive_path = os.path.join(temp_dir, "RJ00000002.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "manual-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {
            "manual_retry_passwords": ["sxy4649777"],
            "manual_retry_password_only": True,
        }

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(side_effect=["unknown", "ok"])
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "test.txt", "size": 12, "is_dir": False}],
        )

        success, password, reason = await extract_service._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=[{
                "password": "sxy4649777",
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == "sxy4649777"
        assert reason == ""
        assert extract_service._probe_password.await_count == 2
        first_probe = extract_service._probe_password.await_args_list[0]
        second_probe = extract_service._probe_password.await_args_list[1]
        assert first_probe.args[1] == ""
        assert first_probe.kwargs["allow_full_test"] is False
        assert second_probe.args[1] == "sxy4649777"
        assert second_probe.kwargs["allow_full_test"] is False
        assert run_7z_command.await_count == 1
        first_cmd = run_7z_command.await_args.args[0]
        assert "-psxy4649777" in first_cmd

    @pytest.mark.asyncio
    async def test_try_extract_large_archive_tries_all_vault_passwords_when_probe_unknown(
        self, extract_service, temp_dir, monkeypatch,
    ):
        """大包探测 unknown 时，密码库候选必须全部进入完整解压验证。"""
        archive_path = os.path.join(temp_dir, "RJ01618696.7z.001")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "auto-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        monkeypatch.setattr(ExtractService, "UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES", 1)
        old_password_list = list(extract_service.config.extract.password_list or [])
        extract_service.config.extract.password_list = []

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"ERROR: CRC Failed in encrypted file. Wrong password? : RJ01618696",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "RJ01618696", "size": 1024, "is_dir": False}],
        )

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "RJ01618696",
                    "source": "RJ号",
                    "entry_id": None,
                    "rjcode": "RJ01618696",
                }, {
                    "password": "vault-a",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }, {
                    "password": "vault-b",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            extract_service.config.extract.password_list = old_password_list

        assert success is False
        assert password is None
        assert reason == "wrong_password"
        assert "extract_unknown_probe_limited" not in (task.task_metadata or {})
        extract_cmds = [
            call.args[0]
            for call in run_7z_command.await_args_list
            if "x" in call.args[0]
        ]
        tried_passwords = [
            next((arg[2:] for arg in cmd if str(arg).startswith("-p")), "")
            for cmd in extract_cmds
        ]
        assert tried_passwords == ["RJ01618696", "RJ01618697", "RJ01618695", "vault-a", "vault-b"]
        fingerprint = extract_service._archive_fingerprint(archive_path)
        assert fingerprint
        tried_key = extract_service._password_cache_key(fingerprint, "RJ01618696")
        tried_plus_key = extract_service._password_cache_key(fingerprint, "RJ01618697")
        tried_minus_key = extract_service._password_cache_key(fingerprint, "RJ01618695")
        tried_generic_key = extract_service._password_cache_key(fingerprint, "vault-a")
        second_generic_key = extract_service._password_cache_key(fingerprint, "vault-b")
        assert tried_key in ExtractService._password_negative_cache
        assert tried_plus_key in ExtractService._password_negative_cache
        assert tried_minus_key in ExtractService._password_negative_cache
        assert tried_generic_key in ExtractService._password_negative_cache
        assert second_generic_key in ExtractService._password_negative_cache

    @pytest.mark.asyncio
    async def test_try_extract_large_unknown_tries_rj_before_generic_passwords(
        self, extract_service, temp_dir, monkeypatch,
    ):
        """大包探测 unknown 时，通用密码不能挤掉 RJ±1 的完整解压机会。"""
        archive_path = os.path.join(temp_dir, "RJ01649862.rar")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "rj-before-generic-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        monkeypatch.setattr(ExtractService, "UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES", 1)

        async def fake_run_7z_command(cmd, *args, **kwargs):
            if "-pRJ01649861" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=2,
                stdout=b"",
                stderr=b"ERROR: CRC Failed in encrypted file. Wrong password? : RJ01649862",
            )

        extract_service._is_rar_archive = Mock(return_value=False)
        extract_service._probe_7z_no_password_status = AsyncMock(return_value="encrypted")
        extract_service._run_7z_command = AsyncMock(side_effect=fake_run_7z_command)
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "RJ01649862/readme.txt", "size": 1024, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": "generic-a",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }, {
                "password": "generic-b",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }, {
                "password": "generic-c",
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == "RJ01649861"
        assert reason == ""
        extract_cmds = [
            call.args[0]
            for call in extract_service._run_7z_command.await_args_list
            if "x" in call.args[0]
        ]
        tried_passwords = [
            next((arg[2:] for arg in cmd if str(arg).startswith("-p")), "")
            for cmd in extract_cmds
        ]
        assert tried_passwords == ["RJ01649862", "RJ01649863", "RJ01649861"]

    @pytest.mark.asyncio
    async def test_try_extract_large_archive_tries_sniffed_password_before_rj_guess(
        self, extract_service, temp_dir, monkeypatch,
    ):
        """大分卷带文件名密码时，应先试文件名嗅探候选，再试 RJ 号猜测。"""
        archive_path = os.path.join(temp_dir, "RJ01618696(southplus@adark).7z.001")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "sniff-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        monkeypatch.setattr(ExtractService, "UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES", 1)

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "RJ01618696", "size": 1024, "is_dir": False}],
        )

        success, password, reason = await extract_service._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=[{
                "password": "southplus@adark",
                "source": "文件名嗅探",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == "southplus@adark"
        assert reason == ""
        first_cmd = run_7z_command.await_args.args[0]
        assert "-psouthplus@adark" in first_cmd

    @pytest.mark.asyncio
    async def test_try_extract_no_password_ignores_stale_negative_cache(
        self, extract_service, temp_dir,
    ):
        """空密码负缓存不能阻止本次轻量探测，否则旧误判会继续影响非加密包。"""
        archive_path = os.path.join(temp_dir, "RJ00000003.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "cache-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        fingerprint = extract_service._archive_fingerprint(archive_path)
        assert fingerprint is not None
        empty_cache_key = extract_service._password_cache_key(fingerprint, "")
        ExtractService._password_negative_cache[empty_cache_key] = 1.0

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._probe_password = AsyncMock(return_value="ok")
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "test.txt", "size": 12, "is_dir": False}],
        )

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "sana",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            ExtractService._password_negative_cache.pop(empty_cache_key, None)

        assert success is True
        assert password == ""
        assert reason == ""
        extract_service._probe_password.assert_awaited_once()
        run_7z_command.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_try_extract_manual_password_ignores_negative_cache(
        self, extract_service, temp_dir,
    ):
        """问题作品里手动指定密码时，旧负缓存不能直接跳过本次尝试。"""
        archive_path = os.path.join(temp_dir, "manual-cache.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "manual-cache-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {
            "manual_retry_passwords": ["sana"],
            "manual_retry_password_only": True,
        }
        fingerprint = extract_service._archive_fingerprint(archive_path)
        cache_key = extract_service._password_cache_key(fingerprint, "sana")
        ExtractService._password_negative_cache[cache_key] = 1.0

        extract_service._probe_password = AsyncMock(side_effect=["unknown", "ok"])
        extract_service._run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        try:
            success, password, reason = await extract_service._try_extract(
                ArchiveInfo(
                    archive_path,
                    [{"name": "test.txt", "size": 12, "is_dir": False}],
                ),
                output_path,
                task,
                password_candidates=[{
                    "password": "sana",
                    "source": "指定密码",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            ExtractService._password_negative_cache.pop(cache_key, None)

        assert success is True
        assert password == "sana"
        assert reason == ""
        extract_service._run_7z_command.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_try_extract_zip_non_ascii_password_uses_python_fallback(
        self, extract_service, temp_dir,
    ):
        """ZIP 中文密码被 7zz 判错时，要进入兼容后端而不是直接写死 wrong_password。"""
        archive_path = os.path.join(temp_dir, "cn-password.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "cn-password-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        password_value = "我chovy，高数你给我出好的啊"
        fingerprint = extract_service._archive_fingerprint(archive_path)
        cache_key = extract_service._password_cache_key(fingerprint, password_value)

        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._try_extract_zip_with_python = AsyncMock(return_value=(True, "cp932"))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))
        extract_service._find_unar_executable = Mock(return_value=None)

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.zip", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == password_value
        assert reason == ""
        extract_service._try_extract_zip_with_python.assert_awaited_once()
        assert cache_key not in ExtractService._password_negative_cache

    @pytest.mark.asyncio
    async def test_try_extract_large_zip_non_ascii_password_prefers_unar(
        self, extract_service, temp_dir,
    ):
        """大 ZIP 中文密码兼容解压优先走 unar，避免 Python zipfile 慢速全量解包。"""
        archive_path = os.path.join(temp_dir, "large-cn-password.zip")
        self.create_test_zip(archive_path)
        os.utime(archive_path, None)
        output_path = os.path.join(temp_dir, "large-cn-password-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        password_value = "我chovy，高数你给我出好的啊"

        extract_service.ZIP_COMPAT_UNAR_FIRST_MIN_BYTES = 1
        extract_service._find_unar_executable = Mock(return_value="/usr/bin/unar")
        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._try_unar_extract = AsyncMock(return_value=subprocess.CompletedProcess(
            args=["unar"],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._try_extract_zip_with_python = AsyncMock(side_effect=AssertionError("大 ZIP 不应先走 Python zipfile"))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.zip", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == password_value
        assert reason == ""
        extract_service._try_unar_extract.assert_awaited_once()
        extract_service._try_extract_zip_with_python.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_try_extract_large_zip_skips_python_zipfile_after_unar_failure(
        self, extract_service, temp_dir,
    ):
        """大 ZIP 的 unar 兼容后端失败后，不允许回退 Python zipfile 全量解压拖死任务。"""
        archive_path = os.path.join(temp_dir, "large-cn-password-unar-fail.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "large-cn-password-unar-fail-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        password_value = "諷詠"

        extract_service.ZIP_COMPAT_UNAR_FIRST_MIN_BYTES = 1
        extract_service._find_unar_executable = Mock(return_value="/usr/bin/unar")
        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._try_unar_extract = AsyncMock(return_value=subprocess.CompletedProcess(
            args=["unar"],
            returncode=1,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._try_extract_zip_with_python = AsyncMock(side_effect=AssertionError("大 ZIP unar 失败后不应回退 Python zipfile"))
        extract_service._cleanup_extract_attempt = AsyncMock()
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.zip", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "密码库-通用",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is False
        assert password is None
        assert reason in {"wrong_password", "unar_failed"}
        extract_service._try_unar_extract.assert_awaited_once()
        extract_service._try_extract_zip_with_python.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_try_extract_large_zip_with_listed_password_uses_python_compat_path(
        self, extract_service, temp_dir,
    ):
        """清单已确认的中文密码不能因大包 unar 策略跳过 Python 兼容解压。"""
        archive_path = os.path.join(temp_dir, "large-cn-password-listed.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "large-cn-password-listed-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        password_value = "我觉得我是"

        extract_service.ZIP_COMPAT_UNAR_FIRST_MIN_BYTES = 1
        extract_service._find_unar_executable = Mock(return_value="/usr/bin/unar")
        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._try_unar_extract = AsyncMock(
            side_effect=AssertionError("已确认密码时不应先走 unar")
        )
        extract_service._try_extract_zip_with_python = AsyncMock(return_value=(True, "utf-8"))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.zip", "size": 10, "is_dir": False}],
                password_value,
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == password_value
        assert reason == ""
        extract_service._try_extract_zip_with_python.assert_awaited_once()
        extract_service._try_unar_extract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_try_extract_manual_large_zip_prefers_python_password_probe(
        self, extract_service, temp_dir,
    ):
        """用户手动指定中文密码时，大 ZIP 也必须先做 Python 多编码验证。"""
        archive_path = os.path.join(temp_dir, "large-cn-password-manual.zip")
        self.create_test_zip(archive_path)
        output_path = os.path.join(temp_dir, "large-cn-password-manual-output")
        os.makedirs(output_path, exist_ok=True)
        password_value = "我觉得我是"
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=archive_path,
            metadata={
                "manual_retry_password": password_value,
                "manual_retry_password_only": True,
            },
        )

        extract_service.ZIP_COMPAT_UNAR_FIRST_MIN_BYTES = 1
        extract_service._find_unar_executable = Mock(return_value="/usr/bin/unar")
        extract_service._probe_zip_no_password_status = Mock(return_value="encrypted")
        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._try_extract_zip_with_python = AsyncMock(return_value=(True, "utf-8"))
        extract_service._try_unar_extract = AsyncMock(
            side_effect=AssertionError("手动密码命中 Python 兼容后端后不应再走 unar")
        )
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.zip", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == password_value
        assert reason == ""
        extract_service._try_extract_zip_with_python.assert_awaited_once()
        extract_service._try_unar_extract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_try_extract_subtitle_probe_allows_large_unencrypted_unknown_probe(
        self, extract_service, temp_dir,
    ):
        """字幕补配不能因未加密大包轻量探测 unknown 而直接放弃扫描字幕。"""
        archive_path = os.path.join(temp_dir, "RJ01656747.7z")
        with open(archive_path, "wb") as fp:
            fp.write(b"placeholder")
        output_path = os.path.join(temp_dir, "subtitle-probe-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=archive_path,
            metadata={"subtitle_probe_mode": True},
        )

        extract_service.UNKNOWN_PROBE_LARGE_ARCHIVE_BYTES = 1
        extract_service._probe_7z_no_password_status = AsyncMock(return_value="plain")
        extract_service._pick_magic_entries = Mock(return_value=[])
        extract_service._pick_probe_entry = Mock(return_value=None)
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=["7zz"],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "subtitle.srt", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[],
        )

        assert success is True
        assert password == ""
        assert reason == ""
        extract_service._run_7z_command.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_try_extract_subtitle_probe_prefers_no_password_before_candidates(
        self, extract_service, temp_dir,
    ):
        """字幕预检遇到 unknown 时，不能因密码库候选跳过无密码完整解压。"""
        archive_path = os.path.join(temp_dir, "RJ01656747-no-password.7z")
        with open(archive_path, "wb") as fp:
            fp.write(b"placeholder")
        output_path = os.path.join(temp_dir, "subtitle-probe-no-password-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=archive_path,
            metadata={"subtitle_probe_mode": True},
        )

        extract_service._probe_7z_no_password_status = AsyncMock(return_value=None)
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=["7zz"],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ))
        extract_service._reject_if_garbled_after_extract = AsyncMock(return_value=False)
        extract_service._verify_extraction = AsyncMock(return_value=True)
        extract_service._cleanup_extract_attempt = AsyncMock()

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "subtitle.srt", "size": 10, "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": "RJ01656747",
                "source": "RJ号",
                "entry_id": None,
                "rjcode": "RJ01656747",
            }],
        )

        assert success is True
        assert password == ""
        assert reason == ""
        extract_service._run_7z_command.assert_awaited_once()
        command = extract_service._run_7z_command.await_args.args[0]
        assert not any(str(arg).startswith("-p") for arg in command)

    def test_probe_zip_password_bytes_ignores_plain_entries(self, extract_service, temp_dir):
        """ZIP 密码字节探测必须用加密条目，不能被未加密小文件误导。"""
        archive_path = os.path.join(temp_dir, "mixed-zipcrypto.zip")
        correct_password = "我chovy，高数你给我出好的啊"
        extract_service.ZIP_PASSWORD_BYTE_PROBE_BYTES = 8
        self.create_gbk_password_zipcrypto_zip_with_plain_entry(
            archive_path,
            correct_password,
            encrypted_payload=b"encrypted payload for crc check",
            plain_name="00-readme.txt",
            plain_payload=b"x",
        )

        assert extract_service._probe_zip_password_bytes(archive_path, "諷詠") is None
        assert extract_service._probe_zip_password_bytes(archive_path, correct_password)[0] in {"gbk", "cp936"}

    @pytest.mark.asyncio
    async def test_try_extract_zip_gbk_password_uses_real_python_fallback(
        self, extract_service, temp_dir,
    ):
        """模拟群晖可解、7zz 按 Unicode 密码失败的 GBK 字节 ZIP 密码。"""
        archive_path = os.path.join(temp_dir, "gbk-password.zip")
        output_path = os.path.join(temp_dir, "gbk-password-output")
        password_value = "我chovy，高数你给我出好的啊"
        self.create_gbk_password_zipcrypto_zip(archive_path, password_value)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {}
        extract_service._probe_password = AsyncMock(return_value="wrong_password")
        extract_service._run_7z_command = AsyncMock(side_effect=AssertionError("不应进入完整 7zz 解压"))

        success, password, reason = await extract_service._try_extract(
            ArchiveInfo(
                archive_path,
                [{"name": "20260604161913.txt", "size": len(b"inner archive payload"), "is_dir": False}],
            ),
            output_path,
            task,
            password_candidates=[{
                "password": password_value,
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }],
        )

        assert success is True
        assert password == password_value
        assert reason == ""
        with open(os.path.join(output_path, "20260604161913.txt"), "rb") as fp:
            assert fp.read() == b"inner archive payload"

    @pytest.mark.asyncio
    async def test_try_extract_sfx_temp_view_incomplete_volume_not_wrong_password(
        self, extract_service, temp_dir,
    ):
        """SFX 临时分卷视图遇到 Unexpected end 时不能被 Wrong password 覆盖。"""
        archive_path = os.path.join(temp_dir, "sfx_view.zip")
        with open(archive_path, "wb") as f:
            f.write(b"PK\x05\x06" + b"\x00" * 18)
        output_path = os.path.join(temp_dir, "sfx-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {
            "exe_e_remap": {
                "mode": "temporary_view",
                "temp_dir": temp_dir,
                "view_map": [{"source": "RJ01629292.exe", "view": archive_path}],
            },
        }

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=(
                b"ERRORS:\n"
                b"Unexpected end of archive\n"
                b"ERROR: Wrong password : sfx_view.zip\n"
            ),
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._cleanup_extract_attempt = AsyncMock()
        old_probe_before_extract = extract_service.PROBE_BEFORE_EXTRACT
        old_password_list = list(extract_service.config.extract.password_list or [])
        extract_service.PROBE_BEFORE_EXTRACT = False
        extract_service.config.extract.password_list = []

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "voice.wav", "size": 12, "is_dir": False}],
            password="bad",
        )

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "bad",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            extract_service.PROBE_BEFORE_EXTRACT = old_probe_before_extract
            extract_service.config.extract.password_list = old_password_list

        assert success is False
        assert password is None
        assert reason == "volume_incomplete"
        assert task.task_metadata["extract_failure_reason"] == "volume_incomplete"
        assert "Unexpected end of archive" in task.task_metadata["sfx_volume_view_error"]
        assert run_7z_command.await_count == 2

    @pytest.mark.asyncio
    async def test_try_extract_sfx_temp_view_headers_error_not_wrong_password(
        self, extract_service, temp_dir,
    ):
        """SFX 临时分卷视图遇到 Headers Error 时也应判为分卷异常。"""
        archive_path = os.path.join(temp_dir, "sfx_view.zip")
        with open(archive_path, "wb") as f:
            f.write(b"PK\x05\x06" + b"\x00" * 18)
        output_path = os.path.join(temp_dir, "sfx-output-headers")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {
            "exe_e_remap": {
                "mode": "temporary_view",
                "temp_dir": temp_dir,
                "view_map": [{"source": "RJ01629292.exe", "view": archive_path}],
            },
        }

        run_7z_command = AsyncMock(return_value=subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"ERROR: Headers Error : sfx_view.zip\n",
        ))
        extract_service._run_7z_command = run_7z_command
        extract_service._cleanup_extract_attempt = AsyncMock()
        old_probe_before_extract = extract_service.PROBE_BEFORE_EXTRACT
        old_password_list = list(extract_service.config.extract.password_list or [])
        extract_service.PROBE_BEFORE_EXTRACT = False
        extract_service.config.extract.password_list = []

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "voice.wav", "size": 12, "is_dir": False}],
            password="bad",
        )

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "bad",
                    "source": "密码库-通用",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            extract_service.PROBE_BEFORE_EXTRACT = old_probe_before_extract
            extract_service.config.extract.password_list = old_password_list

        assert success is False
        assert password is None
        assert reason == "volume_incomplete"
        assert task.task_metadata["extract_failure_reason"] == "volume_incomplete"
        assert "Headers Error" in task.task_metadata["sfx_volume_view_error"]
        assert run_7z_command.await_count >= 1

    @pytest.mark.asyncio
    async def test_try_extract_rar_unar_skips_no_password_when_probe_unknown(
        self, extract_service, temp_dir,
    ):
        """RAR fast-path 也不能在无密码探测不确定时先完整跑 unar。"""
        archive_path = os.path.join(temp_dir, "RJ00000004.rar")
        with open(archive_path, "wb") as f:
            f.write(b"Rar!\x1a\x07\x00")
        output_path = os.path.join(temp_dir, "rar-output")
        os.makedirs(output_path, exist_ok=True)
        task = Task(task_type=TaskType.EXTRACT, source_path=archive_path)
        task.task_metadata = {
            "manual_retry_passwords": ["sxy4649777"],
            "manual_retry_password_only": True,
        }
        old_prefer_unar = extract_service.config.extract.prefer_unar_for_rar
        extract_service.config.extract.prefer_unar_for_rar = True
        extract_service._find_unar_executable = Mock(return_value="unar")
        extract_service._probe_password = AsyncMock(return_value="unknown")
        extract_service._try_extract_rar_with_unar = AsyncMock(
            return_value=(True, "sxy4649777", "")
        )

        archive_info = ArchiveInfo(
            path=archive_path,
            file_list=[{"name": "RJ01378421/偵偭偪壒惡岺朳/僠儍僾僞乕1.wav", "size": 12, "is_dir": False}],
        )

        try:
            success, password, reason = await extract_service._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=[{
                    "password": "sxy4649777",
                    "source": "指定密码",
                    "entry_id": None,
                    "rjcode": None,
                }],
            )
        finally:
            extract_service.config.extract.prefer_unar_for_rar = old_prefer_unar

        assert success is True
        assert password == "sxy4649777"
        assert reason == ""
        extract_service._probe_password.assert_awaited_once()
        unar_passwords = extract_service._try_extract_rar_with_unar.await_args.args[3]
        assert unar_passwords == ["sxy4649777"]

    # ------------------------------------------------------------------
    # _detect_disguised_volume_set：伪装多卷启发式探测
    # ------------------------------------------------------------------
    # 真分卷 7z 至少要 1KB+ 才能过 size 闸门，所以测试里用相对大点的 payload。
    # 内容只需要前 6 字节是 7z 魔数 + 后面凑长度，不要求真能被 7zz 解压。
    _SEVEN_Z_MAGIC = b'7z\xbc\xaf\x27\x1c'

    def _write_fake_volume(self, path, magic_head: bytes, total_size: int):
        """生成一个"前缀是 archive 魔数 + 后续是垃圾数据"的占位文件，用于测探测算法。"""
        with open(path, 'wb') as f:
            f.write(magic_head)
            remaining = total_size - len(magic_head)
            if remaining > 0:
                f.write(b'\x00' * remaining)

    def test_detect_disguised_volume_set_z7_pattern(self, extract_service, temp_dir):
        """伪装 1：``.z7.001 / .z7.002`` 把 7z 写成 z7。

        - 同 prefix ``foo.z7.``、3 位数字 ``001/002``。
        - 首卷魔数为 7z。
        - 应识别为 ``detected_kind='7z'``，suggested_renames 给 ``foo.7z.001``。
        """
        v1 = os.path.join(temp_dir, 'foo.z7.001')
        v2 = os.path.join(temp_dir, 'foo.z7.002')
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=8 * 1024)
        self._write_fake_volume(v2, b'', total_size=8 * 1024)

        result = extract_service._detect_disguised_volume_set(v1)

        assert result is not None
        assert result['detected_kind'] == '7z'
        assert len(result['suspect_files']) == 2
        # suggested 命名严格走 .7z.001 / .7z.002 标准
        new_names = [os.path.basename(item['new']) for item in result['suggested_renames']]
        assert new_names[0].endswith('.7z.001')
        assert new_names[1].endswith('.7z.002')

    def test_detect_disguised_volume_set_skipped_for_lone_file(self, extract_service, temp_dir):
        """孤立文件没有兄弟 → 不应误判。"""
        v1 = os.path.join(temp_dir, 'lonely.7z.001')
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=4 * 1024)
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_skipped_for_non_archive_head(self, extract_service, temp_dir):
        """目录里有"长得像分卷的兄弟"但首卷不是 archive 魔数 → 不应误判。

        典型场景：用户目录下有真的图片序列 cover01.png / cover02.png ...，
        如果探测算法只看文件名规律就会把它们错认成"伪装多卷"。
        """
        v1 = os.path.join(temp_dir, 'cover01.png')
        v2 = os.path.join(temp_dir, 'cover02.png')
        v3 = os.path.join(temp_dir, 'cover03.png')
        # 真 PNG 魔数（不是 archive）
        png_magic = b'\x89PNG\r\n\x1a\n'
        for path in (v1, v2, v3):
            self._write_fake_volume(path, png_magic, total_size=8 * 1024)
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_skipped_for_size_too_small(self, extract_service, temp_dir):
        """单卷 < 1KB → 不应该被误判（小占位文件不可能真是分卷）。"""
        v1 = os.path.join(temp_dir, 'tinyfoo.001')
        v2 = os.path.join(temp_dir, 'tinyfoo.002')
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=200)
        self._write_fake_volume(v2, b'', total_size=200)
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_skipped_for_non_consecutive_indices(self, extract_service, temp_dir):
        """索引不连续（1, 2, 4 缺第 3 卷）→ 不应该判定为分卷。"""
        v1 = os.path.join(temp_dir, 'gappy.z7.001')
        v2 = os.path.join(temp_dir, 'gappy.z7.002')
        v4 = os.path.join(temp_dir, 'gappy.z7.004')  # 缺 003
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=4 * 1024)
        self._write_fake_volume(v2, b'', total_size=4 * 1024)
        self._write_fake_volume(v4, b'', total_size=4 * 1024)
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_skipped_for_size_mismatch(self, extract_service, temp_dir):
        """主体卷大小差异 > 5% → 不应该判定为分卷（真 7z/RAR 中间卷必须严格相等）。"""
        v1 = os.path.join(temp_dir, 'mismatch.z7.001')
        v2 = os.path.join(temp_dir, 'mismatch.z7.002')
        v3 = os.path.join(temp_dir, 'mismatch.z7.003')
        # 1MB / 0.5MB（差 50%）/ 0.5MB —— 主体卷之间已经不一致
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=1024 * 1024)
        self._write_fake_volume(v2, b'', total_size=512 * 1024)
        self._write_fake_volume(v3, b'', total_size=512 * 1024)
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_skipped_for_short_prefix(self, extract_service, temp_dir):
        """prefix 短到只有 1~2 字符 → 算法主动放弃，避免误识别同目录无关短名文件。"""
        v1 = os.path.join(temp_dir, 'a.001')
        v2 = os.path.join(temp_dir, 'a.002')
        self._write_fake_volume(v1, self._SEVEN_Z_MAGIC, total_size=4 * 1024)
        self._write_fake_volume(v2, b'', total_size=4 * 1024)
        # prefix = "a." (2 字符)，被防御闸门挡住
        assert extract_service._detect_disguised_volume_set(v1) is None

    def test_detect_disguised_volume_set_extract_disguised_base_name(self, extract_service):
        """``_extract_disguised_base_name`` 能从典型伪装名里抠出干净 base。"""
        cases = [
            ('foo.z7.001', '7z', 'foo'),
            ('foo.7z.删除001', '7z', 'foo'),
            ('xxx.png', 'zip', 'xxx'),
            ('archive01.png', '7z', 'archive'),
        ]
        for name, kind, expected in cases:
            assert extract_service._extract_disguised_base_name(name, kind) == expected, name

    def test_detect_disguised_volume_set_build_standard_volume_name(self, extract_service):
        """标准命名按 archive_kind 区分：7z / zip 走 ``.NNN``，rar 走 ``.partN.rar``。"""
        assert extract_service._build_standard_volume_name('foo', '7z', 1) == 'foo.7z.001'
        assert extract_service._build_standard_volume_name('foo', '7z', 12) == 'foo.7z.012'
        assert extract_service._build_standard_volume_name('foo', 'rar', 1) == 'foo.part1.rar'
        assert extract_service._build_standard_volume_name('foo', 'rar', 5) == 'foo.part5.rar'
        assert extract_service._build_standard_volume_name('foo', 'zip', 1) == 'foo.zip.001'

    # ------------------------------------------------------------------
    # _clean_disguised_volume_name：剥伪装垃圾字符
    # ------------------------------------------------------------------
    def test_clean_disguised_volume_name_strip_chinese_garbage(self, extract_service):
        """中文 ``删`` / ``删除`` 字符应被剥掉，数字保留作为分卷编号。"""
        assert extract_service._clean_disguised_volume_name('foo.z删02', 'foo') == 'foo.z02'
        assert extract_service._clean_disguised_volume_name('foo.z删03', 'foo') == 'foo.z03'
        assert extract_service._clean_disguised_volume_name('foo.7z.删除001', 'foo') == 'foo.7z.001'
        assert extract_service._clean_disguised_volume_name('foo.r删01', 'foo') == 'foo.r01'

    def test_clean_disguised_volume_name_strip_prefix_disguise_words(self, extract_service):
        """伪装词作为前缀（``删除`` 在 z 之前）也要能剥掉，覆盖用户报告场景。"""
        # 用户实际场景：RJ01358521.删除z02 → RJ01358521.z02
        assert extract_service._clean_disguised_volume_name('RJ01358521.删除z02', 'RJ01358521') == 'RJ01358521.z02'
        assert extract_service._clean_disguised_volume_name('RJ01358521.删除z03', 'RJ01358521') == 'RJ01358521.z03'

    def test_clean_disguised_volume_name_strip_ascii_disguise_words(self, extract_service):
        """ASCII 伪装词（deleted / fake / junk）也应该被剥掉。"""
        assert extract_service._clean_disguised_volume_name('foo.zdeleted02', 'foo') == 'foo.z02'
        assert extract_service._clean_disguised_volume_name('foo.zfake03', 'foo') == 'foo.z03'

    def test_clean_disguised_volume_name_no_change_for_clean(self, extract_service):
        """已经是干净 ASCII 名 + 没有伪装词 → 返回 None（不需要重命名）。"""
        assert extract_service._clean_disguised_volume_name('foo.z01', 'foo') is None
        assert extract_service._clean_disguised_volume_name('foo.7z.001', 'foo') is None
        assert extract_service._clean_disguised_volume_name('foo.part1.rar', 'foo') is None

    def test_clean_disguised_volume_name_invalid_base(self, extract_service):
        """name 不是 ``base + '.' + suffix`` 格式 → 返回 None。"""
        assert extract_service._clean_disguised_volume_name('bar.z删02', 'foo') is None
        assert extract_service._clean_disguised_volume_name('foo', 'foo') is None
        assert extract_service._clean_disguised_volume_name('foo.', 'foo') is None

    def test_clean_disguised_volume_name_no_digits_after_clean(self, extract_service):
        """清理后没有数字 → 不可能是合法分卷，返回 None。"""
        # suffix 全是中文 + 字母，剥完没数字
        assert extract_service._clean_disguised_volume_name('foo.zip删除', 'foo') is None

    # ------------------------------------------------------------------
    # _scan_disguised_supplementary_siblings：volume_set 已识别但有伪装兄弟
    # ------------------------------------------------------------------
    @staticmethod
    def _make_volume_set(base_name: str, volume_paths: list, volume_type: str = 'zip_volume_main'):
        """构造一个最小可用的 VolumeSet 实例承载测试。"""
        from app.core.extract_service import VolumeSet
        return VolumeSet(base_name, volume_paths, volume_type, entry_path=volume_paths[0] if volume_paths else None)

    def test_scan_disguised_supplementary_finds_zip_disguised(self, extract_service, temp_dir):
        """用户报告场景：``xxx.zip + xxx.z01 + xxx.z删02 + xxx.z删03``。

        ``_detect_volume_set`` 因 ``\\.z\\d{2}`` 严格正则只能识别 ``.z01``，但
        ``.z删02 / .z删03`` 才是真正的下游分卷。本扫描必须找出后两个伪装卷。
        """
        zip_path = os.path.join(temp_dir, 'xxx.zip')
        z01_path = os.path.join(temp_dir, 'xxx.z01')
        z02_path = os.path.join(temp_dir, 'xxx.z删02')
        z03_path = os.path.join(temp_dir, 'xxx.z删03')
        # ZIP 魔数 + 占位 1MB（≥ 1KB 闸门）
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=8 * 1024)
        self._write_fake_volume(z01_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z02_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z03_path, b'', total_size=8 * 1024)

        # 模拟 _detect_volume_set 的部分识别结果（只识别到 .zip + .z01）
        volume_set = self._make_volume_set('xxx', [zip_path, z01_path])
        suspects = extract_service._scan_disguised_supplementary_siblings(volume_set)

        assert len(suspects) == 2
        names = sorted([s['name'] for s in suspects])
        assert names == ['xxx.z删02', 'xxx.z删03']
        # 按 index 升序
        assert suspects[0]['index'] == 2
        assert suspects[1]['index'] == 3

    def test_scan_disguised_supplementary_skips_clean_set(self, extract_service, temp_dir):
        """全部是标准命名（``.z01 / .z02``）→ 没有伪装兄弟，返回空。"""
        zip_path = os.path.join(temp_dir, 'clean.zip')
        z01_path = os.path.join(temp_dir, 'clean.z01')
        z02_path = os.path.join(temp_dir, 'clean.z02')
        for p in (zip_path, z01_path, z02_path):
            self._write_fake_volume(p, b'PK\x03\x04', total_size=4 * 1024)

        volume_set = self._make_volume_set('clean', [zip_path, z01_path, z02_path])
        assert extract_service._scan_disguised_supplementary_siblings(volume_set) == []

    def test_scan_disguised_supplementary_skips_small_files(self, extract_service, temp_dir):
        """伪装兄弟卷 < 1KB 应被过滤（防小占位文件被误判为分卷）。"""
        zip_path = os.path.join(temp_dir, 'tiny.zip')
        z01_path = os.path.join(temp_dir, 'tiny.z01')
        tiny_disguised = os.path.join(temp_dir, 'tiny.z删02')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=4 * 1024)
        self._write_fake_volume(z01_path, b'', total_size=4 * 1024)
        # 伪装兄弟只有 200 字节（< 1KB 闸门）
        self._write_fake_volume(tiny_disguised, b'', total_size=200)

        volume_set = self._make_volume_set('tiny', [zip_path, z01_path])
        assert extract_service._scan_disguised_supplementary_siblings(volume_set) == []

    def test_scan_disguised_supplementary_skips_unrelated_prefix(self, extract_service, temp_dir):
        """同目录里有别的工作的伪装文件（base_name 完全不同）→ 不应捞错。"""
        zip_path = os.path.join(temp_dir, 'mywork.zip')
        z01_path = os.path.join(temp_dir, 'mywork.z01')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=4 * 1024)
        self._write_fake_volume(z01_path, b'', total_size=4 * 1024)
        # 同目录里另一个完全无关的工作（不同 base_name）
        unrelated = os.path.join(temp_dir, 'otherwork.z删05')
        self._write_fake_volume(unrelated, b'', total_size=4 * 1024)

        volume_set = self._make_volume_set('mywork', [zip_path, z01_path])
        assert extract_service._scan_disguised_supplementary_siblings(volume_set) == []

    def test_scan_disguised_supplementary_requires_trailing_digits(self, extract_service, temp_dir):
        """suffix 末尾不是数字 → 不应该当成分卷（``.z删ip`` 之类的乱字段）。"""
        zip_path = os.path.join(temp_dir, 'aa.zip')
        z01_path = os.path.join(temp_dir, 'aa.z01')
        # 后缀含中文但末尾不是数字 —— 不是合法的分卷编号
        weird = os.path.join(temp_dir, 'aa.z删ip')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=4 * 1024)
        self._write_fake_volume(z01_path, b'', total_size=4 * 1024)
        self._write_fake_volume(weird, b'', total_size=4 * 1024)

        volume_set = self._make_volume_set('aa', [zip_path, z01_path])
        assert extract_service._scan_disguised_supplementary_siblings(volume_set) == []

    # ------------------------------------------------------------------
    # _maybe_raise_disguised_supplementary：命中即抛 DisguisedVolumeSetError
    # ------------------------------------------------------------------
    def test_maybe_raise_disguised_supplementary_user_zip_scenario(self, extract_service, temp_dir):
        """用户报告场景兜底验证：partial set 命中伪装兄弟 → 抛异常 + 写 metadata。"""
        from app.core.extract_service import DisguisedVolumeSetError
        zip_path = os.path.join(temp_dir, 'xxx.zip')
        z01_path = os.path.join(temp_dir, 'xxx.z01')
        z02_path = os.path.join(temp_dir, 'xxx.z删02')
        z03_path = os.path.join(temp_dir, 'xxx.z删03')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=8 * 1024)
        self._write_fake_volume(z01_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z02_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z03_path, b'', total_size=8 * 1024)

        volume_set = self._make_volume_set('xxx', [zip_path, z01_path])
        task = self._make_task_with_metadata({})

        with pytest.raises(DisguisedVolumeSetError):
            extract_service._maybe_raise_disguised_supplementary(zip_path, task, volume_set)

        # task_metadata 必须写入 disguised_volume_set 标记
        meta = task.task_metadata.get('disguised_volume_set')
        assert isinstance(meta, dict)
        assert meta['detected_kind'] == 'zip'  # 首卷魔数是 PK\x03\x04
        assert meta['confidence'] == 'high'

        # suspect_files：现有 2 卷 + 伪装 2 卷 = 4 卷全在
        names = [s['name'] for s in meta['suspect_files']]
        assert sorted(names) == sorted(['xxx.zip', 'xxx.z01', 'xxx.z删02', 'xxx.z删03'])

        # suggested_renames：标准卷 old==new 不动；伪装卷给"剥掉删"的建议
        rename_map = {os.path.basename(r['old']): os.path.basename(r['new']) for r in meta['suggested_renames']}
        assert rename_map['xxx.zip'] == 'xxx.zip'
        assert rename_map['xxx.z01'] == 'xxx.z01'
        assert rename_map['xxx.z删02'] == 'xxx.z02'
        assert rename_map['xxx.z删03'] == 'xxx.z03'

    def test_maybe_raise_disguised_supplementary_silent_for_clean_set(self, extract_service, temp_dir):
        """全部标准命名 → 静默返回，不抛异常、不污染 metadata。"""
        zip_path = os.path.join(temp_dir, 'ok.zip')
        z01_path = os.path.join(temp_dir, 'ok.z01')
        z02_path = os.path.join(temp_dir, 'ok.z02')
        for p in (zip_path, z01_path, z02_path):
            self._write_fake_volume(p, b'PK\x03\x04', total_size=4 * 1024)

        volume_set = self._make_volume_set('ok', [zip_path, z01_path, z02_path])
        task = self._make_task_with_metadata({})

        # 不应该抛异常
        extract_service._maybe_raise_disguised_supplementary(zip_path, task, volume_set)
        # 不应该写 metadata
        assert 'disguised_volume_set' not in (task.task_metadata or {})

    # ------------------------------------------------------------------
    # _is_disguised_volume_suffix：统一伪装判定
    # ------------------------------------------------------------------
    def test_is_disguised_volume_suffix_non_ascii(self, extract_service):
        """含非 ASCII 字符（中文 / 全角）→ True。"""
        assert extract_service._is_disguised_volume_suffix('z删02') is True
        assert extract_service._is_disguised_volume_suffix('删除z02') is True
        assert extract_service._is_disguised_volume_suffix('7z.删除001') is True

    def test_is_disguised_volume_suffix_ascii_words(self, extract_service):
        """含已知 ASCII 伪装词 → True。"""
        assert extract_service._is_disguised_volume_suffix('zdeleted02') is True
        assert extract_service._is_disguised_volume_suffix('zfake01') is True
        assert extract_service._is_disguised_volume_suffix('zjunk03') is True

    def test_is_disguised_volume_suffix_clean(self, extract_service):
        """纯 ASCII + 没伪装词 → False（不要误伤合法名）。"""
        assert extract_service._is_disguised_volume_suffix('z01') is False
        assert extract_service._is_disguised_volume_suffix('7z.001') is False
        assert extract_service._is_disguised_volume_suffix('part1.rar') is False
        # delta / rmvb 这种"含 del / rm 子串但不是伪装词"的合法名不该被误判
        assert extract_service._is_disguised_volume_suffix('delta01') is False
        assert extract_service._is_disguised_volume_suffix('zip') is False

    def test_is_disguised_volume_suffix_empty(self, extract_service):
        """空字符串 → False。"""
        assert extract_service._is_disguised_volume_suffix('') is False

    # ------------------------------------------------------------------
    # _detect_disguised_set_with_clean_target：target 是干净 archive 名 + 兄弟全伪装
    # ------------------------------------------------------------------
    def test_detect_disguised_set_with_clean_target_user_actual_scenario(self, extract_service, temp_dir):
        """用户实际报告场景：``RJ01358521.zip + .删除z02 + .删除z03``。

        ``_detect_disguised_volume_set`` 因 target ``RJ01358521.zip`` 末尾不是
        数字而无法拆分，原算法直接返回空。本探测专门兜底这种盲区。
        """
        zip_path = os.path.join(temp_dir, 'RJ01358521.zip')
        z02_path = os.path.join(temp_dir, 'RJ01358521.删除z02')
        z03_path = os.path.join(temp_dir, 'RJ01358521.删除z03')
        # 主卷必须有 ZIP 魔数，单卷 ≥ 1KB
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=8 * 1024)
        self._write_fake_volume(z02_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z03_path, b'', total_size=8 * 1024)

        result = extract_service._detect_disguised_set_with_clean_target(zip_path)

        assert result is not None
        assert result['detected_kind'] == 'zip'
        assert result['confidence'] == 'high'  # ≥ 2 个伪装兄弟

        # suspect_files：主卷 + 2 个伪装兄弟 = 3 项
        names = [s['name'] for s in result['suspect_files']]
        assert sorted(names) == sorted(['RJ01358521.zip', 'RJ01358521.删除z02', 'RJ01358521.删除z03'])

        # suggested_renames：主卷 old==new 不动；伪装兄弟剥"删除"后变 .zNN
        rename_map = {os.path.basename(r['old']): os.path.basename(r['new']) for r in result['suggested_renames']}
        assert rename_map['RJ01358521.zip'] == 'RJ01358521.zip'
        assert rename_map['RJ01358521.删除z02'] == 'RJ01358521.z02'
        assert rename_map['RJ01358521.删除z03'] == 'RJ01358521.z03'

    def test_detect_disguised_set_with_clean_target_via_main_entry(self, extract_service, temp_dir):
        """通过 ``_maybe_raise_disguised_volume_set`` 主入口也要能触发新探测分支。

        这是端到端验证：只要 archive_path 是干净 archive 名 + 同目录有伪装兄弟，
        主入口就应该写 metadata + 抛 DisguisedVolumeSetError，让前端走"手动重命名"。
        """
        from app.core.extract_service import DisguisedVolumeSetError
        zip_path = os.path.join(temp_dir, 'RJ01358521.zip')
        z02_path = os.path.join(temp_dir, 'RJ01358521.删除z02')
        z03_path = os.path.join(temp_dir, 'RJ01358521.删除z03')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=8 * 1024)
        self._write_fake_volume(z02_path, b'', total_size=8 * 1024)
        self._write_fake_volume(z03_path, b'', total_size=8 * 1024)

        task = self._make_task_with_metadata({})

        with pytest.raises(DisguisedVolumeSetError):
            extract_service._maybe_raise_disguised_volume_set(zip_path, task)

        meta = task.task_metadata.get('disguised_volume_set')
        assert isinstance(meta, dict)
        assert meta['detected_kind'] == 'zip'
        # rename_map：删除被剥
        rename_map = {os.path.basename(r['old']): os.path.basename(r['new']) for r in meta['suggested_renames']}
        assert rename_map['RJ01358521.删除z02'] == 'RJ01358521.z02'
        assert rename_map['RJ01358521.删除z03'] == 'RJ01358521.z03'

    def test_detect_disguised_set_with_clean_target_skips_lone_archive(self, extract_service, temp_dir):
        """同目录只有干净主卷，没有任何伪装兄弟 → 返回 None。"""
        zip_path = os.path.join(temp_dir, 'lonely.zip')
        self._write_fake_volume(zip_path, b'PK\x03\x04', total_size=8 * 1024)
        assert extract_service._detect_disguised_set_with_clean_target(zip_path) is None

    def test_detect_disguised_set_with_clean_target_skips_non_archive_target(self, extract_service, temp_dir):
        """target 不是合法 archive 后缀（比如 .png）→ 返回 None，不能误吞图片场景。"""
        png_path = os.path.join(temp_dir, 'foo.png')
        # 即使同目录有伪装"兄弟"，也不该触发 —— 因为 target 不是 archive
        sibling = os.path.join(temp_dir, 'foo.删除z02')
        self._write_fake_volume(png_path, b'\x89PNG\r\n\x1a\n', total_size=8 * 1024)
        self._write_fake_volume(sibling, b'', total_size=8 * 1024)
        assert extract_service._detect_disguised_set_with_clean_target(png_path) is None

    def test_detect_disguised_set_with_clean_target_skips_short_base(self, extract_service, temp_dir):
        """base_name < 3 字符 → 放弃，避免误吞同目录无关短名文件。"""
        short_zip = os.path.join(temp_dir, 'ab.zip')
        sibling = os.path.join(temp_dir, 'ab.删除z02')
        self._write_fake_volume(short_zip, b'PK\x03\x04', total_size=8 * 1024)
        self._write_fake_volume(sibling, b'', total_size=8 * 1024)
        assert extract_service._detect_disguised_set_with_clean_target(short_zip) is None

    def test_detect_disguised_set_with_clean_target_falls_back_to_ext_when_magic_bad(self, extract_service, temp_dir):
        """主卷魔数无法识别（如用户造的空主卷）→ 用 target 扩展名兜底，仍能命中。"""
        # 主卷是个空 ZIP（前面没 ZIP 魔数，模拟用户造假主卷）
        broken_zip = os.path.join(temp_dir, 'work.zip')
        sibling = os.path.join(temp_dir, 'work.删除z02')
        with open(broken_zip, 'wb') as f:
            f.write(b'\x00' * (8 * 1024))  # 空内容，没有 PK 魔数
        self._write_fake_volume(sibling, b'', total_size=8 * 1024)

        result = extract_service._detect_disguised_set_with_clean_target(broken_zip)
        assert result is not None
        # 魔数失败，仍按扩展名归类为 zip
        assert result['detected_kind'] == 'zip'

    # ------------------------------------------------------------------
    # 多 RJ 合集预检：覆盖大包内首个子作品命中库存导致整包被判重的回归
    # ------------------------------------------------------------------

    def test_scan_top_level_rjcodes_empty_returns_empty_list(self, extract_service):
        """file_list 为空 / None 都返回空 list，不能抛异常。"""
        assert extract_service._scan_top_level_rjcodes([]) == []
        assert extract_service._scan_top_level_rjcodes(None) == []

    def test_scan_top_level_rjcodes_single_rj_archive(self, extract_service):
        """普通单作品包（顶层就是一个 RJ 目录）只返回 1 个 RJ。"""
        file_list = [
            {"name": "RJ01567971/track01.mp3", "size": 1024, "is_dir": False},
            {"name": "RJ01567971/track02.mp3", "size": 2048, "is_dir": False},
            {"name": "RJ01567971/cover.jpg", "size": 512, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == ["RJ01567971"]

    def test_scan_top_level_rjcodes_multi_rj_top_level(self, extract_service):
        """顶层直接含多个 RJ 目录的合集包必须返回所有 RJ。"""
        file_list = [
            {"name": "RJ01567971/track01.mp3", "size": 1024, "is_dir": False},
            {"name": "RJ01567972/track01.mp3", "size": 1024, "is_dir": False},
            {"name": "RJ01567973/track01.mp3", "size": 1024, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == [
            "RJ01567971",
            "RJ01567972",
            "RJ01567973",
        ]

    def test_scan_top_level_rjcodes_circle_container_with_rj_children(self, extract_service):
        """社团 / 月份容器在顶层、RJ 在第二层，也应识别出全部 RJ。

        典型场景：``[Deep,Dahlia]/RJ0156xxxx/...``。
        """
        file_list = [
            {"name": "[Deep,Dahlia]/RJ01567971/01.mp3", "size": 100, "is_dir": False},
            {"name": "[Deep,Dahlia]/RJ01567972/01.mp3", "size": 100, "is_dir": False},
            {"name": "[Deep,Dahlia]/RJ01567973/01.mp3", "size": 100, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == [
            "RJ01567971",
            "RJ01567972",
            "RJ01567973",
        ]

    def test_scan_top_level_rjcodes_ignores_deep_path_rj(self, extract_service):
        """超过 max_depth 的路径段不应被采集，避免误把内部引用文件名当作独立 RJ。"""
        # 这里 max_depth=3，第 4 层的 RJ 不算
        file_list = [
            {"name": "RJ01567971/subdir/inner/RJ09999999_ref.txt", "size": 10, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list, max_depth=3) == ["RJ01567971"]

    def test_scan_top_level_rjcodes_handles_backslash_paths(self, extract_service):
        """Windows 风格 ``\\`` 分隔符也能正确切分。"""
        file_list = [
            {"name": r"RJ01567971\track01.mp3", "size": 1, "is_dir": False},
            {"name": r"RJ01567972\track01.mp3", "size": 1, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == [
            "RJ01567971",
            "RJ01567972",
        ]

    def test_scan_top_level_rjcodes_dedupes_same_rj(self, extract_service):
        """同一 RJ 在多条 entry 中出现只算一次。"""
        file_list = [
            {"name": "RJ01567971/a.mp3", "size": 1, "is_dir": False},
            {"name": "RJ01567971/b.mp3", "size": 1, "is_dir": False},
            {"name": "RJ01567971/sub/c.mp3", "size": 1, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == ["RJ01567971"]

    def test_scan_top_level_rjcodes_supports_six_digit_rj(self, extract_service):
        """旧版 6 位 RJ（如 RJ123456）也要识别。"""
        file_list = [
            {"name": "RJ123456/foo.wav", "size": 1, "is_dir": False},
            {"name": "RJ234567/foo.wav", "size": 1, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == [
            "RJ123456",
            "RJ234567",
        ]

    def test_scan_top_level_rjcodes_ignores_entries_with_no_rj(self, extract_service):
        """无 RJ 痕迹的条目应被静默跳过，不影响结果。"""
        file_list = [
            {"name": "readme.txt", "size": 1, "is_dir": False},
            {"name": "junk/info.log", "size": 1, "is_dir": False},
            {"name": "RJ01567971/audio.mp3", "size": 1, "is_dir": False},
        ]
        assert extract_service._scan_top_level_rjcodes(file_list) == ["RJ01567971"]

    def test_collect_top_level_rjcodes_returns_empty_for_missing_file(
        self, extract_service, temp_dir
    ):
        """目标路径不存在 → 直接返回空 list，不触碰 7zz。"""
        import asyncio

        missing = os.path.join(temp_dir, 'no_such_archive.zip')
        result = asyncio.run(extract_service.collect_top_level_rjcodes(missing))
        assert result == []

    def test_collect_top_level_rjcodes_uses_archive_info_file_list(
        self, extract_service, temp_dir
    ):
        """复用 ``_get_archive_info`` 的 file_list 输出，正确识别合集包。"""
        import asyncio

        fake_archive = os.path.join(temp_dir, 'big_pack.zip')
        # 写一个最小占位文件，避免 isfile 校验失败
        with open(fake_archive, 'wb') as f:
            f.write(b'PK\x03\x04dummy')

        fake_info = ArchiveInfo(
            path=fake_archive,
            file_list=[
                {"name": "RJ01567971/01.mp3", "size": 1, "is_dir": False},
                {"name": "RJ01567972/01.mp3", "size": 1, "is_dir": False},
                {"name": "[Circle]/RJ01567973/01.mp3", "size": 1, "is_dir": False},
            ],
            password=None,
        )

        with patch.object(
            ExtractService,
            "_get_archive_info",
            new=AsyncMock(return_value=fake_info),
        ):
            result = asyncio.run(extract_service.collect_top_level_rjcodes(fake_archive))

        assert result == ["RJ01567971", "RJ01567972", "RJ01567973"]

    def test_collect_top_level_rjcodes_skips_prefixed_zip_without_running_7z(
        self, extract_service, temp_dir
    ):
        """伪装 ZIP 的可选合集预检不能对原始媒体壳遍历密码库。"""
        import asyncio

        disguised_path = os.path.join(temp_dir, "RJ01303631.mp4")
        offset = self.create_prefixed_zip(disguised_path)
        task = Task(task_type=TaskType.AUTO_PROCESS, source_path=disguised_path)

        with patch.object(
            ExtractService,
            "_get_archive_info",
            new=AsyncMock(side_effect=AssertionError("伪装 ZIP 不应启动 7zz 清单预读")),
        ):
            result = asyncio.run(
                extract_service.collect_top_level_rjcodes(disguised_path, task=task)
            )

        assert result == []
        assert task.task_metadata["embedded_zip_source_path"] == disguised_path
        assert task.task_metadata["embedded_zip_offset"] == offset
        assert "embedded_zip_view_path" not in task.task_metadata

    def test_collect_top_level_rjcodes_returns_empty_on_failure(
        self, extract_service, temp_dir
    ):
        """``_get_archive_info`` 抛异常时回退到空 list，让调用方走原查重逻辑。"""
        import asyncio

        fake_archive = os.path.join(temp_dir, 'broken.zip')
        with open(fake_archive, 'wb') as f:
            f.write(b'PK\x03\x04dummy')

        with patch.object(
            ExtractService,
            "_get_archive_info",
            new=AsyncMock(side_effect=RuntimeError("7zz crashed")),
        ):
            result = asyncio.run(extract_service.collect_top_level_rjcodes(fake_archive))

        assert result == []

    @pytest.mark.asyncio
    async def test_infer_rjcode_skips_large_opaque_inner_entry(self, extract_service, temp_dir):
        """无后缀 opaque 大条目不能为了 RJ 推断整条抽到 temp 再 7zz l。"""
        archive_path = os.path.join(temp_dir, "source.zip")
        with open(archive_path, "wb") as f:
            f.write(b"dummy")
        archive_info = ArchiveInfo(
            archive_path,
            [
                {
                    "name": "payload",
                    "size": extract_service.RJ_INFER_OPAQUE_ENTRY_MAX_SIZE + 1,
                    "is_dir": False,
                },
            ],
            "",
        )
        extract_service._get_archive_info = AsyncMock(return_value=archive_info)
        extract_service.extract_selected_entries = AsyncMock(
            side_effect=AssertionError("大 opaque 条目不应被抽出探测")
        )

        result = await extract_service.infer_rjcode_from_archive(archive_path, max_nested_depth=1)

        assert result is None
        extract_service.extract_selected_entries.assert_not_awaited()

    # ------------------------------------------------------------------
    # 嵌套解压软失败：覆盖合集包内单个嵌套 zip 失败导致整任务被毙的回归
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_subtitle_probe_skips_large_opaque_rar_without_subtitles(
        self, extract_service, temp_dir,
    ):
        output_path = os.path.join(temp_dir, "probe-output")
        os.makedirs(output_path)
        nested_rar = os.path.join(output_path, "RJ01656747")
        with open(nested_rar, "wb") as fp:
            fp.write(b"Rar!\x1a\x07\x01\x00")
            fp.write(b"placeholder")
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, "RJ01656747.7z"),
            metadata={"subtitle_probe_mode": True},
        )
        archive_info = ArchiveInfo(
            nested_rar,
            [{"name": "说明.txt", "size": 128, "is_dir": False}],
            "",
        )

        with patch.object(
            extract_service,
            "_get_archive_info",
            new=AsyncMock(return_value=archive_info),
        ), patch.object(
            extract_service,
            "extract_selected_entries",
            new=AsyncMock(side_effect=AssertionError("无字幕时不应提取任何条目")),
        ), patch.object(
            extract_service,
            "_try_extract_nested_direct",
            new=AsyncMock(side_effect=AssertionError("字幕预检禁止完整解压嵌套 RAR")),
        ):
            result = await extract_service._extract_nested_archives(
                output_path,
                task,
                max_depth=1,
            )

        assert result == 0
        assert task.task_metadata.get("nested_archive_failures") is None
        assert task.task_metadata["nested_archives_without_subtitles"] == ["RJ01656747"]
        assert os.path.exists(nested_rar)

    @pytest.mark.asyncio
    async def test_subtitle_probe_selectively_extracts_entries_from_large_opaque_rar(
        self, extract_service, temp_dir,
    ):
        output_path = os.path.join(temp_dir, "probe-output")
        os.makedirs(output_path)
        nested_rar = os.path.join(output_path, "RJ01656747")
        with open(nested_rar, "wb") as fp:
            fp.write(b"Rar!\x1a\x07\x01\x00")
            fp.write(b"placeholder")
        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, "RJ01656747.7z"),
            metadata={"subtitle_probe_mode": True},
        )
        archive_info = ArchiveInfo(
            nested_rar,
            [
                {"name": "track/voice.lrc", "size": 128, "is_dir": False},
                {"name": "说明.txt", "size": 64, "is_dir": False},
            ],
            "",
        )

        async def fake_extract_selected(_archive, entries, selected_output, **_kwargs):
            assert entries == ["track/voice.lrc"]
            target = os.path.join(selected_output, "track")
            os.makedirs(target, exist_ok=True)
            with open(os.path.join(target, "voice.lrc"), "wb") as fp:
                fp.write(b"[00:00.00]subtitle")
            return selected_output

        with patch.object(
            extract_service,
            "_get_archive_info",
            new=AsyncMock(return_value=archive_info),
        ), patch.object(
            extract_service,
            "extract_selected_entries",
            new=AsyncMock(side_effect=fake_extract_selected),
        ) as selected_mock, patch.object(
            extract_service,
            "_try_extract_nested_direct",
            new=AsyncMock(side_effect=AssertionError("字幕预检禁止完整解压嵌套 RAR")),
        ):
            result = await extract_service._extract_nested_archives(
                output_path,
                task,
                max_depth=1,
            )

        assert result == 1
        assert task.task_metadata.get("nested_archive_failures") is None
        selected_mock.assert_awaited_once()
        assert os.path.exists(os.path.join(output_path, "RJ01656747_1", "track", "voice.lrc"))
        assert os.path.exists(nested_rar)

    def test_extract_nested_archives_part_failure_does_not_raise(
        self, extract_service, temp_dir
    ):
        """嵌套解压部分失败时不应抛 RuntimeError 中断主任务。

        回归用户痛点：117 GB 合集包内 38 个 RJ 解压成功、1 个嵌套奖励 zip 密码错，
        旧实现 raise 后上游 except 调 ``_cleanup_extract_path`` 清空整个 output_path
        导致全军覆没。新实现把失败明细写入 ``task.task_metadata['nested_archive_failures']``，
        不抛异常，让 ``extract()`` 继续走完整性校验、最终兜底、返回 output_path。
        """
        import asyncio

        output_path = os.path.join(temp_dir, 'extract_out')
        os.makedirs(output_path)

        nested_zip = os.path.join(output_path, 'broken_inner.zip')
        self.create_test_zip(nested_zip)

        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, 'outer.zip'),
        )

        with patch.object(
            ExtractService,
            '_classify_nested_small_archive',
            new=AsyncMock(return_value='non_subtitle'),
        ), patch.object(
            ExtractService,
            '_try_extract_nested_direct',
            new=AsyncMock(return_value=(False, None)),
        ):
            result = asyncio.run(extract_service._extract_nested_archives(
                output_path, task, max_depth=1,
            ))

        # 不抛异常，返回 0（无成功）
        assert result == 0

        failures = task.task_metadata.get('nested_archive_failures')
        assert isinstance(failures, list)
        assert len(failures) >= 1
        assert any('broken_inner.zip' in str(item) for item in failures)

        # 失败的源 zip 应仍留在原位，方便后续按 RJ 子任务重试或人工处理
        assert os.path.exists(nested_zip)

    @pytest.mark.asyncio
    async def test_extract_nested_archives_repairs_disguised_sfx_rar_volumes(
        self, extract_service, temp_dir
    ):
        """`.part1.exe + .partN.ra删除r` 应作为一组嵌套 RAR 解压。"""
        output_path = os.path.join(temp_dir, "extract_out")
        os.makedirs(output_path)

        first_volume = os.path.join(output_path, "RJ353111.part1.exe")
        with open(first_volume, "wb") as fp:
            fp.write(b"MZ" + (b"\\0" * 64) + b"Rar!\\x1a\\x07\\x01\\x00")
        for index in (2, 3, 4):
            with open(
                os.path.join(output_path, f"RJ353111.part{index}.ra删除r"),
                "wb",
            ) as fp:
                fp.write(b"Rar!\\x1a\\x07\\x01\\x00payload")

        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, "outer.7z"),
        )

        with patch.object(
            ExtractService,
            "_classify_nested_small_archive",
            new=AsyncMock(return_value="non_subtitle"),
        ), patch.object(
            ExtractService,
            "_try_extract_nested_direct",
            new=AsyncMock(return_value=(True, None)),
        ) as extract_mock:
            result = await extract_service._extract_nested_archives(
                output_path,
                task,
                max_depth=1,
            )

        assert result == 1
        assert extract_mock.await_count == 1
        assert extract_mock.await_args.args[0].endswith("RJ353111.part1.rar")
        assert not os.path.exists(first_volume)
        assert not any(
            name.startswith("RJ353111.part")
            for name in os.listdir(output_path)
        )

    def test_extract_nested_archives_failure_metadata_dedupes(
        self, extract_service, temp_dir
    ):
        """metadata 累积合并：同一任务多层递归不应重复记录同名失败明细。"""
        import asyncio

        output_path = os.path.join(temp_dir, 'extract_out')
        os.makedirs(output_path)

        nested_zip = os.path.join(output_path, 'failing.zip')
        self.create_test_zip(nested_zip)

        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, 'outer.zip'),
        )
        # 预置一条同名失败记录，模拟前一层递归已经写过
        task.task_metadata['nested_archive_failures'] = [
            '嵌套压缩包解压失败: failing.zip',
        ]

        with patch.object(
            ExtractService,
            '_classify_nested_small_archive',
            new=AsyncMock(return_value='non_subtitle'),
        ), patch.object(
            ExtractService,
            '_try_extract_nested_direct',
            new=AsyncMock(return_value=(False, None)),
        ):
            asyncio.run(extract_service._extract_nested_archives(
                output_path, task, max_depth=1,
            ))

        failures = task.task_metadata['nested_archive_failures']
        assert isinstance(failures, list)
        # 同名失败不重复追加
        assert len(failures) == 1
        assert 'failing.zip' in failures[0]

    def test_extract_nested_archives_failure_metadata_resets_on_bad_type(
        self, extract_service, temp_dir
    ):
        """metadata 之前被错误写成非 list（如 str）→ 重置为 list 而非抛错。"""
        import asyncio

        output_path = os.path.join(temp_dir, 'extract_out')
        os.makedirs(output_path)

        nested_zip = os.path.join(output_path, 'failing.zip')
        self.create_test_zip(nested_zip)

        task = Task(
            task_type=TaskType.EXTRACT,
            source_path=os.path.join(temp_dir, 'outer.zip'),
        )
        task.task_metadata['nested_archive_failures'] = 'corrupted_str_value'

        with patch.object(
            ExtractService,
            '_classify_nested_small_archive',
            new=AsyncMock(return_value='non_subtitle'),
        ), patch.object(
            ExtractService,
            '_try_extract_nested_direct',
            new=AsyncMock(return_value=(False, None)),
        ):
            asyncio.run(extract_service._extract_nested_archives(
                output_path, task, max_depth=1,
            ))

        failures = task.task_metadata['nested_archive_failures']
        assert isinstance(failures, list)
        assert any('failing.zip' in str(item) for item in failures)
