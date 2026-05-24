"""
解压服务测试
"""
import pytest
import os
import subprocess
import tempfile
import zipfile
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

    def create_prefixed_zip(self, path):
        """创建前面带 MP4 壳、后面才是 ZIP 的伪装包。"""
        prefix = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00' + (b'\x00' * 128)
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

    def test_file_processor_accepts_prefixed_zip_with_mp4_suffix(self, temp_dir):
        """目录扫描 / watcher 应该把伪装成 .mp4 的 ZIP 也送进入库。"""
        disguised_path = os.path.join(temp_dir, 'movie.mp4')
        self.create_prefixed_zip(disguised_path)

        assert FileProcessor().is_archive(disguised_path) is True
    
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
