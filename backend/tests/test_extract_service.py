"""
解压服务测试
"""
import pytest
import os
import subprocess
import tempfile
import zipfile
from unittest.mock import Mock, AsyncMock, patch

from app.core.extract_service import ArchiveInfo, ExtractService
from app.core.task_engine import Task

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
    
    @pytest.mark.asyncio
    async def test_detect_real_type_zip(self, extract_service, temp_dir):
        """测试检测ZIP文件类型"""
        zip_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(zip_path)
        
        file_type = await extract_service._detect_real_type(zip_path)
        assert file_type == 'zip'
    
    @pytest.mark.asyncio
    async def test_repair_extension(self, extract_service, temp_dir):
        """测试修复文件后缀名"""
        # 创建错误后缀名的文件
        wrong_path = os.path.join(temp_dir, 'test.zi')
        correct_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(wrong_path)
        
        # 修复后缀名
        result = await extract_service._repair_extension(wrong_path)
        
        # 验证
        assert result == correct_path
        assert os.path.exists(correct_path)
        assert not os.path.exists(wrong_path)
    
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
        """7z 内嵌档：remap 应改名为 .7z.001 / .7z.002 / ..."""
        base = os.path.join(temp_dir, 'arc')
        # 在 .exe 头部塞一个 7z 魔数，让探测命中 '7z'
        with open(base + '.exe', 'wb') as f:
            f.write(b'MZ\x00\x00')
            f.write(b'\x00' * 512)
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
        assert new_set.entry_path == base + '.7z.001'
        assert new_set.volumes == [base + '.7z.001', base + '.7z.002', base + '.7z.003']

        # task_metadata 应该记录了 remap 映射，便于失败回滚
        assert 'exe_e_remap' in task.task_metadata
        assert task.task_metadata['exe_e_remap']['inner_format'] == '7z'
        assert task.task_metadata['exe_e_remap']['naming'] == '7z_volume_with_ext'
        assert len(task.task_metadata['exe_e_remap']['rename_map']) == 3

        # 旧文件不应该再存在
        for suffix in ('.exe', '.e01', '.e02'):
            assert not os.path.exists(base + suffix)
        # 新文件应该存在
        for suffix in ('.7z.001', '.7z.002', '.7z.003'):
            assert os.path.exists(base + suffix)

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
        """测试解压验证"""
        # 创建压缩包
        zip_path = os.path.join(temp_dir, 'test.zip')
        self.create_test_zip(zip_path)
        
        # 获取文件信息
        archive_info = await extract_service._get_archive_info(zip_path)
        
        # 解压
        import subprocess
        output_path = os.path.join(temp_dir, 'output')
        os.makedirs(output_path, exist_ok=True)
        subprocess.run(['unzip', zip_path, '-d', output_path], check=True)
        
        # 验证
        result = await extract_service._verify_extraction(archive_info, output_path)
        assert result is True

    @pytest.mark.asyncio
    async def test_extract_task(self, extract_service, temp_dir):
        """测试完整的解压任务"""
        # 创建测试压缩包
        zip_path = os.path.join(temp_dir, 'RJ123456.zip')
        self.create_test_zip(zip_path)
        
        # 创建任务
        task = Mock(spec=Task)
        task.source_path = zip_path
        task.update_progress = Mock()
        
        # 执行解压
        output_path = await extract_service.extract(task)
        
        # 验证
        assert output_path is not None
        assert os.path.exists(output_path)
        assert task.update_progress.called

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

        async def fake_unar_extract(archive_path, output_path, password, task=None):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return subprocess.CompletedProcess(
                    args=['unar'], returncode=1,
                    stdout=b'', stderr=b'Failed! (Wrong password?)',
                )
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

        async def fake_unar_extract(archive_path, output_path, password, task=None):
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
