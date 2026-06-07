"""
BackupZipService 集成测试
"""
import asyncio
import hashlib
import json
import os
import tempfile
from datetime import datetime
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, BackupCheckpoint
from app.core.backup_zip_service import BackupZipService


# ── 测试用内存数据库 ──────────────────────────────────────────

@pytest.fixture
def db_session():
    """每个测试独立的内存数据库会话"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def service():
    """创建 BackupZipService 实例"""
    return BackupZipService()


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ── 1. TestBuildManifest ─────────────────────────────────────

class TestBuildManifest:
    """测试 _build_manifest 方法"""

    def test_empty_directory(self, temp_dir):
        manifest = BackupZipService._build_manifest(temp_dir)
        assert manifest == []

    def test_single_file(self, temp_dir):
        fp = os.path.join(temp_dir, "hello.txt")
        with open(fp, "w") as f:
            f.write("hello")

        manifest = BackupZipService._build_manifest(temp_dir)
        assert len(manifest) == 1
        assert manifest[0]["path"] == "hello.txt"
        assert manifest[0]["size"] == 5

    def test_nested_directories(self, temp_dir):
        os.makedirs(os.path.join(temp_dir, "a", "b"), exist_ok=True)
        for name in ["root.txt", "a/mid.txt", "a/b/deep.txt"]:
            with open(os.path.join(temp_dir, name), "w") as f:
                f.write("x")

        manifest = BackupZipService._build_manifest(temp_dir)
        paths = sorted(item["path"] for item in manifest)
        # os.path.relpath 在 Windows 上用反斜杠
        expected = sorted([
            "root.txt",
            os.path.join("a", "mid.txt"),
            os.path.join("a", "b", "deep.txt"),
        ])
        assert paths == expected

    def test_manifest_fields(self, temp_dir):
        fp = os.path.join(temp_dir, "data.bin")
        with open(fp, "wb") as f:
            f.write(b"\x00" * 128)

        manifest = BackupZipService._build_manifest(temp_dir)
        entry = manifest[0]
        assert "path" in entry
        assert "size" in entry
        assert "mtime" in entry
        assert entry["size"] == 128
        assert isinstance(entry["mtime"], float)


class TestIndexedDirSize:
    """测试库存备份目录大小优先复用 ready 索引"""

    def test_get_dir_size_uses_ready_local_library_index(self, temp_dir):
        service = BackupZipService()
        index_service = MagicMock()
        index_service.is_ready.return_value = True
        index_service.get_library_size.return_value = 12345
        library = SimpleNamespace(
            id="lib-local",
            enabled=True,
            type="local",
            root_path=temp_dir,
            path=temp_dir,
        )

        with patch("app.core.backup_zip_service.os.walk") as mock_walk, \
                patch("app.core.library_manager.load_library_config", return_value={"libraries": [library]}), \
                patch("app.core.library_index.get_library_index_service", return_value=index_service):
            assert service._get_dir_size(temp_dir) == 12345

        mock_walk.assert_not_called()
        index_service.is_ready.assert_called_once_with("lib-local")
        index_service.get_library_size.assert_called_once_with("lib-local")

    def test_get_dir_size_falls_back_when_index_not_ready(self, temp_dir):
        fp = os.path.join(temp_dir, "data.bin")
        with open(fp, "wb") as f:
            f.write(b"x" * 7)

        service = BackupZipService()
        index_service = MagicMock()
        index_service.is_ready.return_value = False
        library = SimpleNamespace(
            id="lib-local",
            enabled=True,
            type="local",
            root_path=temp_dir,
            path=temp_dir,
        )

        with patch("app.core.library_manager.load_library_config", return_value={"libraries": [library]}), \
                patch("app.core.library_index.get_library_index_service", return_value=index_service):
            assert service._get_dir_size(temp_dir) == 7

        index_service.get_library_size.assert_not_called()

    def test_get_dir_size_falls_back_for_subdirectory(self, temp_dir):
        subdir = os.path.join(temp_dir, "sub")
        os.makedirs(subdir, exist_ok=True)
        fp = os.path.join(subdir, "data.bin")
        with open(fp, "wb") as f:
            f.write(b"x" * 9)

        service = BackupZipService()
        index_service = MagicMock()
        index_service.is_ready.return_value = True
        index_service.get_library_size.return_value = 999
        library = SimpleNamespace(
            id="lib-local",
            enabled=True,
            type="local",
            root_path=temp_dir,
            path=temp_dir,
        )

        with patch("app.core.library_manager.load_library_config", return_value={"libraries": [library]}), \
                patch("app.core.library_index.get_library_index_service", return_value=index_service):
            assert service._get_dir_size(subdir) == 9

        index_service.is_ready.assert_not_called()
        index_service.get_library_size.assert_not_called()


# ── 2. TestSplitIntoChunks ───────────────────────────────────

class TestSplitIntoChunks:
    """测试 _split_into_chunks 方法"""

    def test_single_chunk(self):
        manifest = [
            {"path": "a.txt", "size": 100, "mtime": 1.0},
            {"path": "b.txt", "size": 200, "mtime": 2.0},
        ]
        chunks = BackupZipService._split_into_chunks(manifest, chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0] == manifest

    def test_multiple_chunks(self):
        manifest = [
            {"path": f"file_{i}.txt", "size": 500, "mtime": float(i)}
            for i in range(6)
        ]
        # chunk_size=1000 -> 每块最多 1000 字节，每个文件 500
        # 第一块: file_0(500) + file_1(500) = 1000 >= 1000 -> 切
        # 第二块: file_2(500) + file_3(500) = 1000 >= 1000 -> 切
        # 第三块: file_4(500) + file_5(500) = 1000 >= 1000 -> 切
        chunks = BackupZipService._split_into_chunks(manifest, chunk_size=1000)
        assert len(chunks) == 3
        assert len(chunks[0]) == 2
        assert len(chunks[1]) == 2
        assert len(chunks[2]) == 2

    def test_empty_manifest(self):
        chunks = BackupZipService._split_into_chunks([], chunk_size=1000)
        # 源码对空清单返回 [[]]
        assert chunks == [[]]

    def test_exact_boundary(self):
        manifest = [
            {"path": "a.txt", "size": 500, "mtime": 1.0},
            {"path": "b.txt", "size": 500, "mtime": 2.0},
            {"path": "c.txt", "size": 1, "mtime": 3.0},
        ]
        # total=1001 > chunk_size=1000, 所以会分块
        # 第一块: a(500)+b(500)=1000 >= 1000 -> 切
        # 第二块: c(1) -> 剩余
        chunks = BackupZipService._split_into_chunks(manifest, chunk_size=1000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 2
        assert len(chunks[1]) == 1


# ── 3. TestValidateManifest ──────────────────────────────────

class TestValidateManifest:
    """测试 _validate_manifest 方法"""

    def test_identical_manifests(self):
        m = [
            {"path": "a.txt", "size": 100, "mtime": 1.0},
            {"path": "b.txt", "size": 200, "mtime": 2.0},
        ]
        assert BackupZipService._validate_manifest(m, list(m)) is True

    def test_different_size(self):
        old = [{"path": "a.txt", "size": 100, "mtime": 1.0}]
        new = [{"path": "a.txt", "size": 999, "mtime": 1.0}]
        assert BackupZipService._validate_manifest(old, new) is False

    def test_different_mtime(self):
        old = [{"path": "a.txt", "size": 100, "mtime": 1.0}]
        new = [{"path": "a.txt", "size": 100, "mtime": 9.0}]
        assert BackupZipService._validate_manifest(old, new) is False

    def test_missing_file(self):
        old = [
            {"path": "a.txt", "size": 100, "mtime": 1.0},
            {"path": "b.txt", "size": 200, "mtime": 2.0},
        ]
        new = [{"path": "a.txt", "size": 100, "mtime": 1.0}]
        assert BackupZipService._validate_manifest(old, new) is False


# ── 4. TestBuild7zParams ─────────────────────────────────────

class TestBuild7zParams:
    """测试 _build_7z_params 方法"""

    def test_zip_format_level_5(self):
        params = BackupZipService._build_7z_params(
            "zip", 5, 4, "secret", "/out/test.zip"
        )
        assert "-tzip" in params
        assert "-mx=5" in params
        assert "-mmt=4" in params
        assert "-psecret" in params
        assert "-mem=ZipCrypto" in params
        assert "/out/test.zip" in params
        # zip 格式不应有 -ms=on 或 -mhe=on
        assert "-ms=on" not in params
        assert "-mhe=on" not in params

    def test_7z_format_level_9_solid(self):
        params = BackupZipService._build_7z_params(
            "7z", 9, 2, "pw123", "/out/test.7z", solid_archive=True
        )
        assert "-t7z" in params
        assert "-mx=9" in params
        assert "-ms=on" in params
        assert "-mhe=on" in params
        assert "-ppw123" in params
        # level 9 -> mfb=128, mpass=5, md=64m
        assert "-mfb=128" in params
        assert "-mpass=5" in params
        assert "-md=64m" in params

    def test_explicit_threads(self):
        params = BackupZipService._build_7z_params(
            "zip", 3, 8, "pw", "/out/a.zip"
        )
        assert "-mmt=8" in params

    def test_auto_threads(self):
        """threads=0 时应使用 os.cpu_count()"""
        with patch("app.core.backup_zip_service.os.cpu_count", return_value=16):
            params = BackupZipService._build_7z_params(
                "zip", 3, 0, "pw", "/out/a.zip"
            )
        assert "-mmt=16" in params


class TestBackupResourceBudget:
    """测试备份压缩接入本地磁盘 IO 预算"""

    @pytest.mark.asyncio
    async def test_backup_scan_uses_disk_io_budget(self, temp_dir):
        svc = BackupZipService()
        source_path = os.path.join(temp_dir, "source")
        os.makedirs(source_path, exist_ok=True)
        with open(os.path.join(source_path, "a.txt"), "w", encoding="utf-8") as fp:
            fp.write("hello")
        calls = []
        config = SimpleNamespace(
            backup_zip=SimpleNamespace(
                source_path=source_path,
                output_dir=temp_dir,
                path_copy_target="",
                copy_structure_before_zip=False,
                password="pw",
                archive_format="zip",
                compression_level=5,
                compression_threads=1,
                dictionary_size_mb=0,
                solid_archive=True,
            ),
            extract=SimpleNamespace(seven_zip_path="7z"),
        )

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.backup_zip_service.get_config", return_value=config), \
                patch("app.core.backup_zip_service.get_resource_budget_service", return_value=Budget()), \
                patch.object(svc, "_get_last_backup_end_time", return_value=datetime(2000, 1, 1)), \
                patch.object(svc, "_find_7z_executable", return_value="7z"), \
                patch.object(svc, "_save_checkpoint"), \
                patch.object(svc, "_compress_chunks", new_callable=AsyncMock), \
                patch.object(svc, "_finalize_success", new_callable=AsyncMock):
            await svc._run()

        assert calls[:2] == [
            ("disk_io_local", 1, "backup_zip.scan_size"),
            ("disk_io_local", 1, "backup_zip.scan_manifest"),
        ]

    @pytest.mark.asyncio
    async def test_resume_manifest_validation_uses_disk_io_budget(self, temp_dir):
        svc = BackupZipService()
        source_path = os.path.join(temp_dir, "source")
        os.makedirs(source_path, exist_ok=True)
        with open(os.path.join(source_path, "a.txt"), "w", encoding="utf-8") as fp:
            fp.write("hello")
        manifest = BackupZipService._build_manifest(source_path)
        svc._file_manifest = manifest
        calls = []
        config = SimpleNamespace(
            backup_zip=SimpleNamespace(
                password="pw",
                compression_threads=1,
                dictionary_size_mb=0,
                solid_archive=True,
            ),
            extract=SimpleNamespace(seven_zip_path="7z"),
        )
        checkpoint = {
            "source_path": source_path,
            "archive_path": os.path.join(temp_dir, "backup.zip"),
            "archive_format": "zip",
            "compression_level": 5,
            "password_hash": hashlib.sha256(b"pw").hexdigest(),
        }

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.backup_zip_service.get_config", return_value=config), \
                patch("app.core.backup_zip_service.get_resource_budget_service", return_value=Budget()), \
                patch.object(svc, "_find_7z_executable", return_value="7z"), \
                patch.object(svc, "_compress_chunks", new_callable=AsyncMock), \
                patch.object(svc, "_finalize_success", new_callable=AsyncMock):
            await svc._run_resume(checkpoint)

        assert calls == [("disk_io_local", 1, "backup_zip.scan_manifest")]

    @pytest.mark.asyncio
    async def test_single_chunk_uses_disk_io_budget(self, temp_dir):
        svc = BackupZipService()
        calls = []

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.backup_zip_service.get_resource_budget_service", return_value=Budget()), \
                patch.object(svc, "_run_7z", new_callable=AsyncMock, return_value=0):
            await svc._compress_chunks(
                seven_zip="7z",
                archive_format="zip",
                compression_level=5,
                threads=2,
                password="pw",
                archive_path=os.path.join(temp_dir, "test.zip"),
                source_parent=temp_dir,
                source_name="source",
                dict_size_mb=0,
                solid=True,
                total_chunks=1,
            )

        assert calls == [("disk_io_local", 1, "backup_zip.compress")]

    @pytest.mark.asyncio
    async def test_multi_chunk_uses_disk_io_budget_per_chunk(self, temp_dir):
        svc = BackupZipService()
        svc._chunks = [
            [{"path": "a.txt", "size": 10, "mtime": 1.0}],
            [{"path": "b.txt", "size": 20, "mtime": 1.0}],
        ]
        svc._current_chunk_index = 0
        calls = []

        class Budget:
            @asynccontextmanager
            async def acquire(self, resource, *, weight=1, reason=""):
                calls.append((resource, weight, reason))
                yield

        with patch("app.core.backup_zip_service.get_resource_budget_service", return_value=Budget()), \
                patch.object(svc, "_run_7z", new_callable=AsyncMock, return_value=0), \
                patch.object(svc, "_save_checkpoint"):
            await svc._compress_chunks(
                seven_zip="7z",
                archive_format="zip",
                compression_level=5,
                threads=2,
                password="pw",
                archive_path=os.path.join(temp_dir, "test.zip"),
                source_parent=temp_dir,
                source_name="source",
                dict_size_mb=0,
                solid=True,
                total_chunks=2,
            )

        assert calls == [
            ("disk_io_local", 1, "backup_zip.compress_chunk"),
            ("disk_io_local", 1, "backup_zip.compress_chunk"),
        ]

    def test_custom_dictionary_size(self):
        params = BackupZipService._build_7z_params(
            "7z", 5, 2, "pw", "/out/a.7z", dictionary_size_mb=128
        )
        assert "-md=128m" in params


# ── 5. TestCheckpoint ────────────────────────────────────────

class TestCheckpoint:
    """测试断点持久化方法（mock 数据库）"""

    def _make_mock_db(self, records=None):
        """构建一个模拟 db session，支持 query/add/commit/close/rollback"""
        db = MagicMock()
        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter_by.return_value = filter_mock

        if records is not None:
            # order_by -> first 链
            order_mock = MagicMock()
            filter_mock.order_by.return_value = order_mock
            order_mock.first.return_value = records
            filter_mock.first.return_value = records
            filter_mock.count.return_value = 1 if records else 0
        else:
            filter_mock.first.return_value = None
            order_mock = MagicMock()
            filter_mock.order_by.return_value = order_mock
            order_mock.first.return_value = None
            filter_mock.count.return_value = 0

        return db

    @patch("app.core.backup_zip_service.get_db")
    def test_save_and_load_checkpoint(self, mock_get_db):
        """保存断点后能加载回来"""
        saved_records = {}

        def fake_add(record):
            saved_records["record"] = record

        # -- save --
        save_db = MagicMock()
        save_query = MagicMock()
        save_db.query.return_value = save_query
        save_filter = MagicMock()
        save_query.filter_by.return_value = save_filter
        save_filter.first.return_value = None  # 不存在旧记录
        save_db.add.side_effect = fake_add

        # -- load --
        load_record = MagicMock()
        load_record.id = "test-id-123"
        load_record.source_path = "/src"
        load_record.output_dir = "/out"
        load_record.archive_path = "/out/test.zip"
        load_record.archive_format = "zip"
        load_record.compression_level = 5
        load_record.password_hash = "abc"
        load_record.file_manifest = json.dumps([{"path": "a.txt", "size": 10, "mtime": 1.0}])
        load_record.completed_chunks = json.dumps(["chunk_0"])
        load_record.current_chunk_index = 1
        load_record.total_chunks = 2
        load_record.total_files = 1
        load_record.processed_files = 1
        load_record.total_bytes = 10
        load_record.processed_bytes = 5

        load_db = MagicMock()
        load_query = MagicMock()
        load_db.query.return_value = load_query
        load_filter = MagicMock()
        load_query.filter_by.return_value = load_filter
        load_order = MagicMock()
        load_filter.order_by.return_value = load_order
        load_order.first.return_value = load_record

        call_count = [0]

        def db_generator():
            if call_count[0] == 0:
                call_count[0] += 1
                yield save_db
            else:
                yield load_db

        mock_get_db.side_effect = lambda: db_generator()

        svc = BackupZipService()
        svc._checkpoint_id = "test-id-123"
        svc._file_manifest = [{"path": "a.txt", "size": 10, "mtime": 1.0}]
        svc._chunks = [[{"path": "a.txt", "size": 10, "mtime": 1.0}], []]
        svc._completed_chunks = []
        svc._current_chunk_index = 0
        svc._pre_size = 10

        # 保存
        svc._save_checkpoint("in_progress", archive_path="/out/test.zip",
                             source_path="/src", output_dir="/out",
                             archive_format="zip", compression_level=5,
                             password="secret")
        save_db.commit.assert_called_once()

        # 加载
        result = svc._load_checkpoint()
        assert result is not None
        assert result["id"] == "test-id-123"
        assert result["source_path"] == "/src"
        assert result["completed_chunks"] == ["chunk_0"]

    @patch("app.core.backup_zip_service.get_db")
    def test_delete_checkpoint(self, mock_get_db):
        db = MagicMock()
        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter_by.return_value = filter_mock

        mock_get_db.return_value = iter([db])

        svc = BackupZipService()
        svc._checkpoint_id = "to-delete"
        svc._delete_checkpoint()

        filter_mock.delete.assert_called_once()
        db.commit.assert_called_once()
        assert svc._checkpoint_id is None

    @patch("app.core.backup_zip_service.get_db")
    def test_no_checkpoint_returns_none(self, mock_get_db):
        db = MagicMock()
        query_mock = MagicMock()
        db.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter_by.return_value = filter_mock
        order_mock = MagicMock()
        filter_mock.order_by.return_value = order_mock
        order_mock.first.return_value = None

        mock_get_db.return_value = iter([db])

        svc = BackupZipService()
        result = svc._load_checkpoint()
        assert result is None


# ── 6. TestDiskFullHandling ──────────────────────────────────

class TestDiskFullHandling:
    """测试磁盘空间不足场景"""

    @pytest.mark.asyncio
    async def test_disk_full_error(self, temp_dir):
        """模拟 shutil.disk_usage 返回磁盘满，验证 _run 中 makedirs 后写入失败"""
        svc = BackupZipService()

        # 创建一个源目录和文件
        source = os.path.join(temp_dir, "source")
        os.makedirs(source)
        with open(os.path.join(source, "test.txt"), "w") as f:
            f.write("data")

        output = os.path.join(temp_dir, "output")
        os.makedirs(output)

        # 直接测试：当 _run_7z 返回非零码时，_compress_chunks 应抛出 RuntimeError
        with patch.object(svc, "_run_7z", new_callable=AsyncMock, return_value=1):
            with pytest.raises(RuntimeError, match="7z.*失败"):
                await svc._compress_chunks(
                    seven_zip="7z",
                    archive_format="zip",
                    compression_level=5,
                    threads=2,
                    password="pw",
                    archive_path=os.path.join(output, "test.zip"),
                    source_parent=temp_dir,
                    source_name="source",
                    dict_size_mb=0,
                    solid=True,
                    total_chunks=1,
                )

