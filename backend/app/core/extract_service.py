import os
import re
import shutil
import subprocess
import asyncio
import sys
import filetype
import tempfile
from typing import Optional, List, Dict, Callable, Union
from pathlib import Path
import logging
from datetime import datetime

from ..config.settings import get_config
from ..core.task_engine import Task
from ..core.password_utils import (
    normalize_filename_value,
    normalize_password_value,
    normalize_rjcode_value,
)

logger = logging.getLogger(__name__)

# Windows 上隐藏子进程窗口的标志
if sys.platform == 'win32':
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

class ArchiveInfo:
    """压缩包信息"""
    def __init__(
        self,
        path: str,
        file_list: List[Dict],
        password: Optional[str] = None,
        inferred_rjcode: Optional[str] = None,
    ):
        self.path = path
        self.file_list = file_list  # [{"name": "...", "size": 123, "crc": "..."}, ...]
        self.password = password
        self.inferred_rjcode = inferred_rjcode
        self.is_volume = False
        self.volume_set: Optional[List[str]] = None

class ExtractService:
    """解压服务"""

    _seven_zip_available_cache: Optional[bool] = None
    _seven_zip_available_path: Optional[str] = None
    _seven_zip_check_lock: Optional[asyncio.Lock] = None
    _seven_zip_semaphore: Optional[asyncio.Semaphore] = None
    _seven_zip_semaphore_limit: Optional[int] = None
    
    @property
    def config(self):
        """动态获取最新配置"""
        from ..config.settings import get_config
        return get_config()
    
    @property
    def seven_zip(self) -> str:
        """动态获取7z路径"""
        return self._find_7z_executable()
    
    def _find_7z_executable(self) -> str:
        """查找 7z 可执行文件"""
        import shutil
        
        # 首先尝试配置的路径
        configured_path = self.config.extract.seven_zip_path
        if configured_path and configured_path != "7z":
            if os.path.exists(configured_path):
                return configured_path
        
        # 尝试在 PATH 中查找
        seven_zip_path = shutil.which("7z")
        if seven_zip_path:
            return seven_zip_path
        
        # Windows 默认安装路径
        default_paths = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ]
        
        for path in default_paths:
            if os.path.exists(path):
                return path
        
        # 如果都找不到，返回配置的值（后续会报错）
        logger.error("找不到 7z 可执行文件。请安装 7-Zip 并确保它在 PATH 中，或在配置中指定正确路径。")
        return "7z"
    
    async def _ensure_7z_available(self) -> bool:
        """异步检查 7z 是否可用，并缓存结果避免高并发重复探测"""
        executable = self.seven_zip
        if (
            self.__class__._seven_zip_available_cache is not None
            and self.__class__._seven_zip_available_path == executable
        ):
            return bool(self.__class__._seven_zip_available_cache)

        if self.__class__._seven_zip_check_lock is None:
            self.__class__._seven_zip_check_lock = asyncio.Lock()

        async with self.__class__._seven_zip_check_lock:
            if (
                self.__class__._seven_zip_available_cache is not None
                and self.__class__._seven_zip_available_path == executable
            ):
                return bool(self.__class__._seven_zip_available_cache)

            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    [executable, "--help"],
                    capture_output=True,
                    timeout=5
                )
                available = result.returncode == 0
            except Exception as e:
                logger.error(f"检查 7z 可用性失败: {e}")
                available = False

            self.__class__._seven_zip_available_cache = available
            self.__class__._seven_zip_available_path = executable
            return available

    def _get_7z_semaphore(self) -> asyncio.Semaphore:
        configured_workers = max(1, int(self.config.processing.max_workers or 1))
        limit = max(1, min(configured_workers, 2 if configured_workers <= 4 else 3))
        if (
            self.__class__._seven_zip_semaphore is None
            or self.__class__._seven_zip_semaphore_limit != limit
        ):
            self.__class__._seven_zip_semaphore = asyncio.Semaphore(limit)
            self.__class__._seven_zip_semaphore_limit = limit
            logger.info("设置 7z 并发上限: %s", limit)
        return self.__class__._seven_zip_semaphore
    
    async def extract(self, task: Task) -> Optional[str]:
        """
        解压压缩包
        返回解压后的目录路径
        """
        # 首先检查 7z 是否可用
        if not await self._ensure_7z_available():
            raise Exception("找不到 7z 可执行文件。请安装 7-Zip 并确保它在 PATH 中，或在配置中指定正确路径。")
        
        archive_path = task.source_path
        
        # 检查是否被取消
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 已被取消，跳过解压")
            return None
        
        # 1. 等待文件稳定
        task.update_progress(5, "等待文件写入完成")
        await self._wait_file_stable(archive_path, task)
        
        # 检查暂停和取消
        await task.wait_if_paused()
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 在等待文件稳定后被取消")
            return None
        
        # 2. 修复后缀名
        task.update_progress(10, "检测文件类型")
        archive_path = await self._repair_extension(archive_path)

        # 更新任务的 source_path，确保归档时使用正确的路径
        if archive_path != task.source_path:
            logger.info(f"[Extract] 文件路径已更新: {task.source_path} -> {archive_path}")
            task.source_path = archive_path
        
        # 3. 检查是否是分卷
        volume_set = self._detect_volume_set(archive_path)
        if volume_set:
            task.update_progress(15, "等待分卷组完整")
            if not await self._wait_for_complete_set(volume_set, task):
                raise Exception("分卷组不完整或等待超时")
            archive_path = volume_set.entry_path or volume_set.volumes[0]

        # 3.5 如果密码库是按文件名匹配到的，且条目里带 RJ 号，则只注入 RJ 提示。
        # 不改源文件名，避免监控链路还在等旧路径导致超时。
        password_candidates = await self._get_password_candidates_for_archive(archive_path)
        hinted_rjcode = self._apply_filename_password_rj_hint(archive_path, task, password_candidates)
        
        # 检查暂停和取消
        await task.wait_if_paused()
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 在等待分卷后被取消")
            return None
        
        # 4. 获取压缩包内文件列表
        task.update_progress(20, "读取压缩包内容")
        archive_info = await self._get_archive_info(archive_path)
        archive_info_from_listing = archive_info is not None
        if not archive_info:
            logger.warning("预读取压缩包内容失败，回退为直接尝试解压: %s", archive_path)
            archive_info = ArchiveInfo(archive_path, [], None)
            task.update_progress(24, "压缩包预读失败，尝试直接解压")
        
        # 5. 确定输出路径
        output_name = str(hinted_rjcode or Path(archive_path).stem).strip()  # 去除首尾空格，避免Windows路径错误
        # 移除其他Windows不允许的字符
        output_name = re.sub(r'[<>:"|?*]', '', output_name)
        output_path = tempfile.mkdtemp(
            prefix=f"{output_name}_{task.id[:8]}_",
            dir=self.config.storage.temp_path
        )
        
        # 6. 尝试解压
        task.update_progress(30, "开始解压")
        success, success_password = await self._try_extract(
            archive_info,
            output_path,
            task,
            password_candidates=password_candidates,
        )
        
        if not success:
            # 更新任务状态为失败，并设置错误信息
            error_msg = "解压失败：无正确密码"
            task.fail(error_msg)
            logger.error(f"任务 {task.id}: {error_msg}")
            # 清理已创建的解压目录（包括部分解压的残留文件）
            await self._cleanup_extract_path(output_path)
            return None
        
        # 记录成功使用的密码
        logger.info(f"外层压缩包解压成功，使用密码: {success_password or '无密码'}")
        
        # 检查暂停和取消
        await task.wait_if_paused()
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 在解压完成后被取消，清理已解压文件")
            import shutil
            if os.path.exists(output_path):
                shutil.rmtree(output_path)
            return None
        
        # 7. 验证解压完整性
        if archive_info_from_listing:
            task.update_progress(90, "验证解压完整性")
            if not await self._verify_extraction(archive_info, output_path):
                raise Exception("解压验证失败，文件不完整")
        else:
            logger.warning("解压前未能读取到压缩包目录，跳过基于清单的完整性校验: %s", archive_path)
        
        # 8. 检查并解压嵌套压缩包
        if self.config.extract.extract_nested_archives:
            task.update_progress(95, "检查嵌套压缩包")
            nested_count = await self._extract_nested_archives(
                output_path, 
                task, 
                max_depth=self.config.extract.max_nested_depth,
                parent_password=success_password  # 传递成功使用的密码给嵌套压缩包
            )
            if nested_count > 0:
                logger.info(f"解压了 {nested_count} 个嵌套压缩包")
        else:
            logger.debug("嵌套压缩包解压已禁用")
        
        return output_path

    def _pick_filename_matched_rjcode(self, password_candidates: List[Dict[str, Optional[str]]]) -> Optional[str]:
        for item in password_candidates or []:
            if item.get("source") != "密码库-文件名":
                continue
            normalized_rjcode = normalize_rjcode_value(item.get("rjcode"))
            if normalized_rjcode:
                return normalized_rjcode
        return None

    def _apply_filename_password_rj_hint(
        self,
        archive_path: str,
        task: Task,
        password_candidates: List[Dict[str, Optional[str]]],
    ) -> Optional[str]:
        matched_rjcode = self._pick_filename_matched_rjcode(password_candidates)
        if not matched_rjcode:
            return None

        if task.task_metadata is None:
            task.task_metadata = {}
        task.task_metadata.setdefault("inferred_rjcode", matched_rjcode)
        task.task_metadata.setdefault("rjcode", matched_rjcode)
        task.task_metadata["inferred_rjcode_source"] = "password_entry_filename_match"
        if not getattr(task, "rjcode", None) or str(task.rjcode).strip() in {"", "未知"}:
            task.rjcode = matched_rjcode
        logger.info("[Extract] 密码库按文件名命中 RJ，仅注入任务上下文，不改源文件名: source=%s rj=%s", archive_path, matched_rjcode)
        return matched_rjcode

    async def get_archive_info(self, archive_path: str) -> Optional[ArchiveInfo]:
        """Public wrapper for archive listing."""
        return await self._get_archive_info(archive_path)

    async def extract_selected_entries(
        self,
        archive_path: str,
        entry_names: List[str],
        output_path: Optional[str] = None,
    ) -> str:
        """
        Extract only the selected archive entries into a temporary directory.

        This reuses the existing password discovery flow and preserves the
        original relative paths inside the archive.
        """
        if not await self._ensure_7z_available():
            raise RuntimeError("找不到 7z 可执行文件，无法提取指定条目")

        normalized_entries: List[str] = []
        seen_entries = set()
        for item in entry_names or []:
            name = str(item or "").strip()
            if not name or name in seen_entries:
                continue
            seen_entries.add(name)
            normalized_entries.append(name)

        if not normalized_entries:
            raise ValueError("没有可提取的压缩包条目")

        archive_info = await self._get_archive_info(archive_path)
        if not archive_info:
            archive_info = ArchiveInfo(archive_path, [], None)

        created_temp_dir = False
        if output_path:
            os.makedirs(output_path, exist_ok=True)
        else:
            safe_name = re.sub(r'[<>:\"|?*]', '', Path(archive_path).stem.strip()) or "selected_extract"
            output_path = tempfile.mkdtemp(
                prefix=f"{safe_name}_selected_",
                dir=self.config.storage.temp_path
            )
            created_temp_dir = True

        list_file_path = os.path.join(output_path, "_selected_entries.txt")
        with open(list_file_path, "w", encoding="utf-8", newline="\n") as fp:
            for name in normalized_entries:
                fp.write(name)
                fp.write("\n")

        def cleanup_attempt_output():
            for name in os.listdir(output_path):
                current_path = os.path.join(output_path, name)
                if os.path.abspath(current_path) == os.path.abspath(list_file_path):
                    continue
                try:
                    if os.path.isdir(current_path):
                        shutil.rmtree(current_path, ignore_errors=True)
                    else:
                        os.remove(current_path)
                except Exception:
                    logger.debug("清理选择性解压残留失败: %s", current_path, exc_info=True)

        password_candidates = await self._get_password_candidates_for_archive(archive_info.path)
        vault_passwords = [item["password"] for item in password_candidates]
        rj_passwords = self._get_rj_passwords(archive_info.path)
        password_list = []
        password_list.extend(rj_passwords)
        password_list.extend(vault_passwords)
        if archive_info.password and archive_info.password not in password_list:
            password_list.append(archive_info.password)
        password_list.append("")
        password_list.extend(self.config.extract.password_list)

        seen_passwords = set()
        unique_passwords = []
        for password in password_list:
            if password in seen_passwords:
                continue
            seen_passwords.add(password)
            unique_passwords.append(password)

        for password in unique_passwords:
            cleanup_attempt_output()
            password_args = [f"-p{password}"] if password else ["-p"]
            cmd = [
                self.seven_zip,
                "x",
                "-y",
                f"-o{output_path}",
                *password_args,
                archive_info.path,
                f"@{list_file_path}",
            ]

            result = await self._run_7z_command(cmd)
            if result.returncode == 0:
                archive_info.password = password
                return output_path

        cleanup_attempt_output()
        if created_temp_dir:
            try:
                os.remove(list_file_path)
            except OSError:
                pass
        raise RuntimeError("选择性解压失败：未能使用现有密码策略提取目标条目")
    
    async def _extract_nested_archives(self, directory: str, task: Task, max_depth: int = 5, current_depth: int = 0, processed_paths: Optional[set] = None, parent_password: Optional[str] = None) -> int:
        """
        递归解压目录中的嵌套压缩包
        
        Args:
            directory: 要检查的目录
            task: 任务对象
            max_depth: 最大递归深度
            current_depth: 当前递归深度
            processed_paths: 已处理的文件路径集合（防止循环）
            parent_password: 外层压缩包使用的密码（优先尝试）
        
        Returns:
            解压的嵌套压缩包数量
        """
        if processed_paths is None:
            processed_paths = set()
        
        # 检查深度限制
        if current_depth >= max_depth:
            logger.warning(f"达到最大嵌套深度 {max_depth}，停止解压嵌套压缩包")
            return 0
        
        # 检查任务状态
        if task.is_cancelled():
            logger.info("任务被取消，停止解压嵌套压缩包")
            return 0
        await task.wait_if_paused()
        
        extracted_count = 0
        archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'}
        
        # 扫描目录中的所有文件
        try:
            for root, dirs, files in os.walk(directory):
                # 检查任务状态
                if task.is_cancelled():
                    break
                await task.wait_if_paused()
                
                for filename in files:
                    file_path = os.path.join(root, filename)
                    
                    # 检查是否已经处理过（防止循环）
                    file_real_path = os.path.realpath(file_path)
                    if file_real_path in processed_paths:
                        logger.debug(f"跳过已处理的文件: {filename}")
                        continue
                    
                    # 检查后缀名或通过魔数检测
                    is_archive = False
                    ext = Path(filename).suffix.lower()
                    
                    if ext in archive_extensions:
                        is_archive = True
                    else:
                        # 通过后缀名无法识别，尝试魔数检测
                        is_archive = await self._detect_by_magic_bytes(file_path) is not None
                    
                    if is_archive:
                        # 检查是否是分卷文件（跳过非首卷）
                        import re
                        part_match = re.search(r'\.part(\d+)\.', filename, re.IGNORECASE)
                        if part_match and int(part_match.group(1)) > 1:
                            continue
                        if re.search(r'\.z\d{2}$', filename, re.IGNORECASE):
                            continue
                        
                        logger.info(f"发现嵌套压缩包: {filename} (深度: {current_depth + 1}, 父密码: {parent_password or '无'})")
                        
                        # 检查任务状态
                        if task.is_cancelled():
                            break
                        await task.wait_if_paused()
                        
                        # 确定解压目标目录
                        # 如果压缩包名是 123.zip，解压到 123/ 目录
                        archive_name = Path(filename).stem
                        nested_output_dir = os.path.join(root, archive_name)
                        
                        # 如果目录已存在，添加序号
                        counter = 1
                        original_output_dir = nested_output_dir
                        while os.path.exists(nested_output_dir):
                            nested_output_dir = f"{original_output_dir}_{counter}"
                            counter += 1
                        
                        os.makedirs(nested_output_dir, exist_ok=True)
                        
                        # 尝试解压嵌套压缩包
                        try:
                            # 首先尝试使用父密码读取压缩包信息
                            nested_archive_info = await self._get_nested_archive_info(file_path, parent_password)
                            
                            if nested_archive_info:
                                task.update_progress(
                                    95, 
                                    f"解压嵌套压缩包 {filename} (层{current_depth + 1})"
                                )
                                
                                # 使用相同的密码策略解压
                                success, nested_success_password = await self._try_extract_nested(
                                    nested_archive_info, 
                                    nested_output_dir, 
                                    task,
                                    parent_password
                                )
                                
                                # 如果失败，尝试从密码库获取密码
                                if not success:
                                    logger.info(f"使用常规密码解压嵌套压缩包失败，尝试从密码库查找密码: {filename}")
                                    vault_passwords = await self._get_passwords_for_archive(file_path)
                                    if vault_passwords:
                                        for pwd in vault_passwords:
                                            if pwd != nested_archive_info.password and pwd != parent_password:
                                                logger.info(f"尝试使用密码库密码解压嵌套压缩包: {filename}")
                                                # 重新获取压缩包信息
                                                new_info = await self._get_nested_archive_info(file_path, pwd)
                                                if new_info:
                                                    success, nested_success_password = await self._try_extract_nested(
                                                        new_info, 
                                                        nested_output_dir, 
                                                        task,
                                                        pwd
                                                    )
                                                    if success:
                                                        nested_archive_info = new_info
                                                        break
                                
                                if success:
                                    logger.info(f"成功解压嵌套压缩包: {filename} (使用密码: {nested_success_password or '无密码'})")
                                    extracted_count += 1
                                    
                                    # 标记为已处理
                                    processed_paths.add(file_real_path)
                                    
                                    # 删除原始的嵌套压缩包文件
                                    try:
                                        # 检查是否是分卷压缩包
                                        volume_set = self._detect_volume_set(file_path)
                                        if volume_set:
                                            # 如果是分卷压缩包，删除所有相关分卷
                                            for volume_path in volume_set.volumes:
                                                if os.path.exists(volume_path):
                                                    os.remove(volume_path)
                                                    logger.info(f"已删除嵌套压缩包分卷文件: {volume_path}")
                                        else:
                                            # 只是普通单文件压缩包
                                            os.remove(file_path)
                                            logger.info(f"已删除嵌套压缩包文件: {file_path}")
                                    except Exception as e:
                                        logger.warning(f"删除嵌套压缩包文件失败: {file_path}, 错误: {e}")
                                    
                                    # 递归检查解压出来的目录，传递成功使用的密码
                                    sub_count = await self._extract_nested_archives(
                                        nested_output_dir, 
                                        task, 
                                        max_depth, 
                                        current_depth + 1,
                                        processed_paths,
                                        nested_success_password  # 传递成功使用的密码给下一层
                                    )
                                    extracted_count += sub_count
                                else:
                                    logger.warning(f"无法解压嵌套压缩包: {filename} (已尝试所有密码)")
                                    # 清理失败的解压目录
                                    if os.path.exists(nested_output_dir):
                                        import shutil
                                        shutil.rmtree(nested_output_dir)
                            else:
                                logger.warning(f"无法读取嵌套压缩包内容: {filename}")
                        
                        except Exception as e:
                            logger.error(f"解压嵌套压缩包失败 {filename}: {e}")
                            # 清理失败的解压目录
                            if os.path.exists(nested_output_dir):
                                import shutil
                                shutil.rmtree(nested_output_dir)
        
        except Exception as e:
            logger.error(f"扫描嵌套压缩包时出错: {e}")
        
        return extracted_count
    
    async def _get_nested_archive_info(self, archive_path: str, parent_password: Optional[str] = None) -> Optional[ArchiveInfo]:
        """
        获取嵌套压缩包信息
        尝试所有可能的密码，返回能找到的第一个可用密码
        """
        # 构建密码列表：父密码优先，然后无密码，最后通用密码
        password_list = []
        
        # 1. 优先尝试父密码
        if parent_password:
            password_list.append(parent_password)
        
        # 2. 尝试无密码
        password_list.append("")
        
        # 3. 尝试通用密码
        password_list.extend(self.config.extract.password_list)
        
        # 去重（保持顺序）
        seen = set()
        unique_passwords = []
        for pwd in password_list:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)
        
        # 尝试所有密码，找到能读取内容的
        for password in unique_passwords:
            file_list = await self._list_archive_contents(archive_path, password)
            if file_list is not None:
                source = "父密码" if password == parent_password else ("无密码" if password == "" else "通用密码")
                logger.info(f"成功读取嵌套压缩包内容，使用: {source} ({password or '无密码'})")
                return ArchiveInfo(archive_path, file_list, password)
        
        return None
    
    async def _try_extract_nested(self, archive_info: ArchiveInfo, output_path: str, task: Task, parent_password: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        尝试解压嵌套压缩包
        尝试所有可能的密码：已知的密码、父密码、无密码、通用密码
        返回 (是否成功, 成功使用的密码)
        """
        # 构建完整的密码列表
        password_list = []
        
        # 1. 首先尝试已知的密码（从 _get_nested_archive_info 获取的）
        if archive_info.password:
            password_list.append((archive_info.password, "已知密码"))
        
        # 2. 尝试父密码（如果和已知密码不同）
        if parent_password and parent_password != archive_info.password:
            password_list.append((parent_password, "父密码"))
        
        # 3. 尝试无密码（如果还没试过）
        if "" != archive_info.password and "" != parent_password:
            password_list.append(("", "无密码"))
        
        # 4. 尝试通用密码（配置中的密码列表）
        for pwd in self.config.extract.password_list:
            if pwd and pwd != archive_info.password and pwd != parent_password:
                password_list.append((pwd, "通用密码"))
        
        logger.info(f"开始尝试解压嵌套压缩包，共 {len(password_list)} 个密码")
        
        for password, source in password_list:
            cmd = [
                self.seven_zip, 'x',
                '-y',  # 自动确认
                '-o' + output_path,  # 输出目录
                archive_info.path
            ]
            
            if password:
                cmd.append(f'-p{password}')
            else:
                cmd.append('-p')  # 空密码
            
            try:
                logger.info(f"尝试解压嵌套压缩包使用: {source} ({password or '无密码'})")
                result = await self._run_7z_command(cmd)
                
                if result.returncode == 0:
                    logger.info(f"嵌套压缩包解压成功，使用: {source} ({password or '无密码'})")
                    # 更新archive_info中的密码，用于传递给下一层
                    archive_info.password = password
                    return True, password
                else:
                    logger.warning(f"密码 {source} ({password or '无密码'}) 解压失败")
                
            except Exception as e:
                logger.warning(f"嵌套压缩包解压尝试失败: {e}")
                continue
        
        logger.error(f"嵌套压缩包解压失败，已尝试所有 {len(password_list)} 个密码")
        return False, None
    
    async def _wait_file_stable(self, file_path: str, task: Optional[Task] = None, max_wait: int = 3600):
        """等待文件大小稳定（文件复制完成检测）"""
        config = self.config.processing
        previous_size = -1
        stable_count = 0
        start_time = asyncio.get_event_loop().time()
        last_progress_time = start_time
        
        logger.info(f"开始等待文件复制完成: {file_path}")
        
        while stable_count < config.file_stable_checks:
            current_time = asyncio.get_event_loop().time()
            
            # 检查总超时
            if current_time - start_time > max_wait:
                raise TimeoutError(f"等待文件复制完成超时 ({max_wait}秒): {file_path}")
            
            # 检查任务是否被取消
            if task and task.is_cancelled():
                logger.info(f"任务在等待文件复制时被取消: {file_path}")
                return
            
            # 检查任务是否暂停
            if task:
                await task.wait_if_paused()
            
            try:
                # 检查文件是否存在
                if not os.path.exists(file_path):
                    await asyncio.sleep(config.file_stable_interval)
                    continue
                
                # 获取文件大小
                current_size = os.path.getsize(file_path)
                
                # 检查文件是否为空或太小（可能是刚开始复制）
                if current_size < 1024:  # 小于1KB认为可能是刚开始复制
                    logger.debug(f"文件太小 ({current_size} bytes)，等待更多数据写入...")
                    await asyncio.sleep(config.file_stable_interval)
                    continue
                
                # 检查文件大小是否稳定
                if current_size == previous_size:
                    stable_count += 1
                    # 尝试打开文件检查是否被锁定
                    try:
                        with open(file_path, 'rb') as f:
                            # 尝试读取文件开头（检查是否可以访问）
                            f.read(1)
                        # 如果成功读取且稳定次数达标，认为文件已复制完成
                        if stable_count >= config.file_stable_checks:
                            logger.info(f"文件复制完成检测通过: {file_path} ({current_size} bytes)")
                            return
                    except (PermissionError, OSError):
                        # 文件仍被锁定，重置稳定计数
                        logger.debug(f"文件仍被锁定，继续等待: {file_path}")
                        stable_count = 0
                else:
                    # 文件大小在变化，正在复制中
                    if stable_count > 0:
                        logger.info(f"文件仍在复制中，当前大小: {current_size} bytes")
                    stable_count = 0
                    last_progress_time = current_time
                
                previous_size = current_size
                
                # 如果长时间没有进度，发出警告
                if current_time - last_progress_time > 60:  # 1分钟没有变化
                    logger.warning(f"文件复制可能已停滞: {file_path}, 当前大小: {current_size} bytes")
                    
            except Exception as e:
                logger.warning(f"等待文件稳定时出错: {e}")
                await asyncio.sleep(config.file_stable_interval)
                continue
            
            await asyncio.sleep(config.file_stable_interval)
    
    async def _repair_extension(self, file_path: str) -> str:
        """修复文件后缀名和文件名
        
        处理情况：
        1. 有常见压缩后缀名但类型不匹配 → 修复后缀名
        2. 无后缀名或后缀名不常见，但检测到是压缩文件 → 规范化文件名并添加正确的后缀名
        
        文件名规范化：
        - 39.RJ01570159 → RJ01570159.rar
        - 01503161 → RJ01503161.zip
        """
        if not self.config.extract.auto_repair_extension:
            return file_path
        
        filename = Path(file_path).name
        current_ext = Path(file_path).suffix.lower()
        
        # 跳过自解压文件（.exe）
        if filename.lower().endswith('.exe'):
            logger.info(f"跳过自解压文件后缀名修复: {file_path}")
            return file_path
        
        # 跳过分卷压缩文件
        import re
        if re.search(r'\.part\d+\.(rar|zip|7z)$', filename, re.IGNORECASE):
            logger.info(f"跳过分卷压缩文件后缀名修复: {file_path}")
            return file_path
        
        # 跳过无扩展名的分卷压缩文件 (.part1, .part2, ...)
        if re.search(r'\.part\d+$', filename, re.IGNORECASE):
            logger.info(f"跳过无扩展名的分卷压缩文件后缀名修复: {file_path}")
            return file_path
        
        # 跳过 ZIP 分卷压缩文件 (.z01, .z02, ...)
        if re.search(r'\.z\d+$', filename, re.IGNORECASE):
            logger.info(f"跳过 ZIP 分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 跳过 7z 分卷压缩文件 (.7z.001, .7z.002, ...)
        if re.search(r'\.7z\.\d{3}$', filename, re.IGNORECASE):
            logger.info(f"跳过 7z 分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}
        
        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if not real_type:
            logger.warning(f"无法检测文件类型: {file_path}")
            return file_path
        
        correct_ext = self._get_correct_extension(real_type)
        
        # 情况1: 文件有常见压缩后缀名，检查是否需要修复
        if current_ext in common_archive_extensions:
            if current_ext != f".{correct_ext}":
                new_path = self._rename_with_extension(file_path, correct_ext)
                logger.info(f"修复后缀名: {file_path} -> {new_path}")
                return new_path
            return file_path
        
        # 情况2: 文件无后缀名或后缀名不常见，但检测到是压缩文件
        # 需要规范化文件名并添加后缀名
        # 注意：使用完整文件名而不是 stem，因为 Path.suffix 可能误识别
        # 例如：39.RJ01570159 的 stem 是 "39"，suffix 是 ".RJ01570159"
        full_filename = Path(file_path).name  # 获取完整文件名
        normalized_name = self._normalize_filename(full_filename)
        new_path = self._rename_with_normalized_name(file_path, normalized_name, correct_ext)
        logger.info(f"规范文件名并添加后缀: {file_path} -> {new_path}")
        return new_path
    
    def _normalize_filename(self, filename: str) -> str:
        """规范化文件名，提取或构造RJ号
        
        例如:
        - 39.RJ01570159 → RJ01570159
        - 01503161 → RJ01503161
        - RJ123456 → RJ123456
        """
        # 先匹配标准RJ号格式，8位优先于6位
        rj_match = re.search(r'[RVB]J(\d{8}|\d{6})(?!\d)', filename, re.IGNORECASE)
        if rj_match:
            return rj_match.group(0).upper()
        
        # 匹配纯数字，8位优先于6位
        num_match = re.search(r'(\d{8}|\d{6})(?!\d)', filename)
        if num_match:
            return f"RJ{num_match.group(1)}"
        
        return filename
    
    def _rename_with_normalized_name(self, file_path: str, new_name: str, ext: str) -> str:
        """用规范化的文件名重命名文件并添加后缀"""
        path = Path(file_path)
        new_filename = f"{new_name}.{ext}"
        new_path = path.parent / new_filename
        
        counter = 1
        while new_path.exists():
            new_filename = f"{new_name}({counter}).{ext}"
            new_path = path.parent / new_filename
            counter += 1
        
        os.rename(file_path, new_path)
        return str(new_path)
    
    async def normalize_archive_filename(self, file_path: str) -> str:
        """规范化压缩包文件名（在任务创建前调用）

        如果文件名需要规范化，会重命名文件并返回新路径
        如果不需要规范化，返回原路径

        对于分卷压缩文件，会统一规范化整个分卷组
        """
        if not self.config.extract.auto_repair_extension:
            return file_path

        path = Path(file_path)
        filename = path.name
        current_ext = path.suffix.lower()

        # 检查是否是分卷压缩文件
        volume_set = self._detect_volume_set(file_path)
        if volume_set:
            # 对于 .7z.xxx 格式的分卷，完全跳过规范化（这种格式已经是正确的）
            if volume_set.type == '7z_volume_with_ext':
                logger.info(f"[VolumeNormalize] .7z.xxx 格式的分卷，跳过规范化: {filename}")
                return file_path
            return await self._normalize_volume_set(file_path, volume_set)

        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}

        # 如果文件已有常见压缩后缀名，不需要规范化文件名
        if current_ext in common_archive_extensions:
            return file_path
        
        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if not real_type:
            logger.info(f"[Normalize] 无法检测文件类型，保持原样: {file_path}")
            return file_path

        correct_ext = self._get_correct_extension(real_type)

        # 规范化文件名
        normalized_name = self._normalize_filename(filename)

        # 检查是否需要重命名
        # 1. 文件名需要规范化
        # 2. 或者文件缺少后缀需要添加
        need_rename = normalized_name != filename

        # 检查文件是否缺少后缀（当前无后缀或后缀不是常见压缩格式）
        current_has_valid_ext = current_ext in common_archive_extensions

        if not need_rename and current_has_valid_ext:
            # 文件名已规范化且有有效后缀，无需处理
            return file_path

        if not need_rename and not current_has_valid_ext:
            # 文件名已规范化但缺少后缀，只添加后缀
            new_filename = f"{normalized_name}.{correct_ext}"
            new_path = os.path.join(os.path.dirname(file_path), new_filename)
            logger.info(f"[RENAME] 添加缺失的后缀: {file_path} -> {new_path}")

            # 处理重名
            counter = 1
            while os.path.exists(new_path):
                new_filename = f"{normalized_name}({counter}).{correct_ext}"
                new_path = os.path.join(os.path.dirname(file_path), new_filename)
                counter += 1

            os.rename(file_path, new_path)
            return new_path

        # 文件名需要规范化，重命名文件
        new_path = self._rename_with_normalized_name(file_path, normalized_name, correct_ext)
        logger.info(f"[RENAME] 文件名规范化: {file_path} -> {new_path}")
        return new_path
    
    async def _normalize_volume_set(self, file_path: str, volume_set: 'VolumeSet') -> str:
        """规范化分卷压缩包组的文件名

        例如: 39.RJ123456.part1.rar, 39.RJ123456.part2.rar -> RJ123456.part1.rar, RJ123456.part2.rar

        对于 .7z.xxx 格式的分卷，保持 .7z.xxx 后缀不变
        """
        base_name = volume_set.base_name
        vtype = volume_set.type

        # 对于 .7z.xxx 格式的分卷，完全跳过规范化（这种格式是正确的）
        if vtype == '7z_volume_with_ext':
            # 检查首卷文件名格式
            first_volume = volume_set.entry_path or (volume_set.volumes[0] if volume_set.volumes else file_path)
            first_filename = os.path.basename(first_volume)
            # 检查是否符合 RJxxxxxx.7z.001 格式（RJ号开头，然后是 .7z.分卷号）
            if re.match(r'^RJ\d+\.7z\.\d{3}$', first_filename, re.IGNORECASE):
                logger.info(f"[VolumeNormalize] 分卷文件名已是标准格式，无需修改: {first_filename}")
                return file_path

        normalized_base = self._normalize_filename(base_name)

        logger.info(f"[VolumeNormalize] base_name={base_name}, normalized_base={normalized_base}, vtype={vtype}")

        if normalized_base == base_name:
            logger.info(f"分卷组文件名无需规范化: {base_name}")
            return file_path

        directory = os.path.dirname(file_path)
        rename_map = []

        for volume_path in volume_set.volumes:
            volume_filename = os.path.basename(volume_path)
            pattern = self._get_volume_pattern(volume_filename)
            logger.info(f"[VolumeNormalize] 处理分卷: {volume_filename}, pattern={pattern}")
            if pattern:
                suffix = pattern.group(0)
                new_filename = f"{normalized_base}{suffix}"
                new_path = os.path.join(directory, new_filename)
                rename_map.append((volume_path, new_path))
                logger.info(f"[VolumeNormalize] 计划重命名: {volume_filename} -> {new_filename}")

        if not rename_map:
            logger.warning(f"[VolumeNormalize] 没有找到需要重命名的分卷文件")
            return file_path

        for old_path, new_path in rename_map:
            if old_path != new_path and os.path.exists(old_path):
                os.rename(old_path, new_path)
                logger.info(f"[RENAME] 分卷重命名: {old_path} -> {new_path}")

        target_entry_path = volume_set.entry_path or file_path
        for old_path, new_path in rename_map:
            if old_path == target_entry_path:
                return new_path
        return rename_map[0][1]
    
    def _get_volume_pattern(self, filename: str) -> Optional[re.Match]:
        """获取分卷后缀模式匹配"""
        patterns = [
            r'\.7z\.\d{3}$',                # .7z.001, .7z.002 (7z分卷，带.7z扩展名)
            r'\.part\d+\.(rar|zip|7z)$',  # 带扩展名的分卷
            r'\.part\d+$',                  # 无扩展名的分卷 (如 .part1)
            r'\.z\d{2}$',
            r'\.r\d{2}$',
            r'\.zip$',
            r'\.rar$',
            r'\.\d{3}$',
            r'\.\d{2}$',
        ]
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return match
        return None
    
    def _get_volume_set_normalized_filename(self, file_path: str, volume_set: 'VolumeSet') -> Optional[str]:
        """获取分卷组规范化后的首卷文件名（不执行重命名）
        
        返回首卷的规范化文件名，如果不需要规范化则返回 None
        """
        base_name = volume_set.base_name
        normalized_base = self._normalize_filename(base_name)
        
        if normalized_base == base_name:
            logger.debug(f"[Normalize] 分卷组文件名无需规范化: {base_name}")
            return None
        
        first_volume = volume_set.entry_path or (volume_set.volumes[0] if volume_set.volumes else file_path)
        first_filename = os.path.basename(first_volume)
        pattern = self._get_volume_pattern(first_filename)
        
        if pattern:
            suffix = pattern.group(0)
            result = f"{normalized_base}{suffix}"
            logger.info(f"[Normalize] 需要规范化分卷组: {base_name} -> {normalized_base}, 首卷: {first_filename} -> {result}")
            return result
        
        return None
    
    async def get_normalized_filename(self, file_path: str) -> Optional[str]:
        """获取规范化后的文件名（不执行重命名）
        
        返回规范化后的完整文件名，如果不需要规范化则返回 None
        
        对于分卷压缩文件，返回首卷的规范化文件名
        """
        if not self.config.extract.auto_repair_extension:
            logger.debug(f"[Normalize] auto_repair_extension 未启用")
            return None
        
        path = Path(file_path)
        filename = path.name
        current_ext = path.suffix.lower()
        
        logger.debug(f"[Normalize] 检查文件: {filename}, 当前后缀: {current_ext}")
        
        # 检查是否是分卷压缩文件
        volume_set = self._detect_volume_set(file_path)
        if volume_set:
            return self._get_volume_set_normalized_filename(file_path, volume_set)
        
        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}
        
        # 如果文件已有常见压缩后缀名，不需要规范化
        if current_ext in common_archive_extensions:
            logger.debug(f"[Normalize] 已有常见压缩后缀，跳过: {current_ext}")
            return None
        
        # 规范化文件名
        normalized_name = self._normalize_filename(filename)
        logger.debug(f"[Normalize] 规范化结果: {filename} -> {normalized_name}")
        
        if normalized_name == filename:
            logger.debug(f"[Normalize] 文件名不需要变化")
            return None
        
        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if real_type:
            correct_ext = self._get_correct_extension(real_type)
            logger.debug(f"[Normalize] 检测到类型: {real_type}, 正确后缀: {correct_ext}")
        else:
            # 如果检测不到类型，尝试从文件名推断
            if re.search(r'\.(rar|zip|7z)$', filename, re.IGNORECASE):
                match = re.search(r'\.(rar|zip|7z)$', filename, re.IGNORECASE)
                correct_ext = match.group(1).lower()
            else:
                # 默认使用 rar
                correct_ext = 'rar'
            logger.debug(f"[Normalize] 无法检测类型，使用默认: {correct_ext}")
        
        result = f"{normalized_name}.{correct_ext}"
        logger.info(f"[Normalize] 需要规范化: {filename} -> {result}")
        return result
    
    async def _detect_real_type(self, file_path: str) -> Optional[str]:
        """检测文件真实类型"""
        # 方法1: 使用 filetype 库（添加重试机制）
        max_retries = 3
        for retry in range(max_retries):
            try:
                kind = filetype.guess(file_path)
                if kind:
                    return kind.extension
                break
            except PermissionError:
                if retry < max_retries - 1:
                    logger.warning(f"文件访问被拒绝，等待后重试 ({retry + 1}/{max_retries}): {file_path}")
                    await asyncio.sleep(2)  # 等待2秒再试
                else:
                    logger.error(f"文件访问被拒绝，跳过 filetype 检测: {file_path}")
        
        # 方法2: 使用 7z 测试
        try:
            result = await self._run_7z_command([self.seven_zip, 'l', file_path])
            if result.returncode == 0:
                # 从输出中检测格式
                output = result.stdout.decode('utf-8', errors='ignore')
                if 'Type = 7z' in output:
                    return '7z'
                elif 'Type = zip' in output:
                    return 'zip'
                elif 'Type = rar' in output:
                    return 'rar'
        except Exception as e:
            logger.error(f"7z检测失败: {e}")
        
        # 方法3: 魔数检测
        magic_result = await self._detect_by_magic_bytes(file_path)
        return magic_result
    
    async def _detect_by_magic_bytes(self, file_path: str) -> Optional[str]:
        """通过魔数检测文件类型"""
        magic_bytes = {
            b'PK\x03\x04': 'zip',
            b'PK\x05\x06': 'zip',  # 空zip
            b'PK\x07\x08': 'zip',  # zip64
            b'Rar!': 'rar',
            b'7z\xBC\xAF\x27\x1C': '7z',
        }
        
        # 添加重试机制
        max_retries = 3
        for retry in range(max_retries):
            try:
                with open(file_path, 'rb') as f:
                    header = f.read(8)
                    for magic, file_type in magic_bytes.items():
                        if header.startswith(magic):
                            return file_type
                break
            except PermissionError:
                if retry < max_retries - 1:
                    logger.warning(f"魔数检测文件访问被拒绝，等待后重试 ({retry + 1}/{max_retries}): {file_path}")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"魔数检测文件访问被拒绝: {file_path}")
            except Exception as e:
                logger.error(f"魔数检测失败: {e}")
                break
        
        return None
    
    def _get_correct_extension(self, file_type: str) -> str:
        """获取正确的后缀名"""
        extension_map = {
            'zip': 'zip',
            'rar': 'rar',
            '7z': '7z',
            'gz': 'gz',
            'bz2': 'bz2',
            'xz': 'xz',
        }
        return extension_map.get(file_type, file_type)
    
    def _rename_with_extension(self, file_path: str, new_ext: str) -> str:
        """重命名文件并修改后缀（用于已有错误后缀的文件）"""
        path = Path(file_path)
        new_name = f"{path.stem}.{new_ext}"
        new_path = path.parent / new_name
        
        counter = 1
        while new_path.exists():
            new_name = f"{path.stem}({counter}).{new_ext}"
            new_path = path.parent / new_name
            counter += 1
        
        os.rename(file_path, new_path)
        return str(new_path)
    
    def _add_extension(self, file_path: str, ext: str) -> str:
        """为文件添加后缀名（用于无后缀或后缀不正确的压缩文件）
        
        例如: 39.RJ01570159 -> 39.RJ01570159.rar
              01503161 -> 01503161.zip
        """
        path = Path(file_path)
        new_name = f"{path.name}.{ext}"
        new_path = path.parent / new_name
        
        counter = 1
        while new_path.exists():
            new_name = f"{path.name}({counter}).{ext}"
            new_path = path.parent / new_name
            counter += 1
        
        os.rename(file_path, new_path)
        return str(new_path)
    
    def _detect_volume_set(self, file_path: str) -> Optional['VolumeSet']:
        """检测是否是分卷压缩包"""
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)

        zip_main_match = re.search(r'^(?P<base>.+)\.zip$', filename, re.IGNORECASE)
        zip_part_match = re.search(r'^(?P<base>.+)\.z\d{2}$', filename, re.IGNORECASE)
        if zip_main_match or zip_part_match:
            base_name = (zip_main_match or zip_part_match).group('base')
            volume_set = self._build_zip_volume_set(directory, base_name)
            if volume_set:
                logger.info(f"[VolumeSet] 检测到 ZIP 分卷组: {base_name}")
                return volume_set

        rar_main_match = re.search(r'^(?P<base>.+)\.rar$', filename, re.IGNORECASE)
        rar_part_match = re.search(r'^(?P<base>.+)\.r\d{2}$', filename, re.IGNORECASE)
        if rar_main_match or rar_part_match:
            base_name = (rar_main_match or rar_part_match).group('base')
            volume_set = self._build_rar_old_volume_set(directory, base_name)
            if volume_set:
                logger.info(f"[VolumeSet] 检测到旧式 RAR 分卷组: {base_name}")
                return volume_set

        # 分卷模式识别（按优先级排序，更具体的模式在前）
        patterns = [
            (r'\.7z\.(\d{3})$', '7z_volume_with_ext'),  # .7z.001, .7z.002 (7z分卷，带.7z扩展名)
            (r'\.part(\d+)\.(rar|zip|7z)$', 'part'),
            (r'\.part(\d+)$', 'part_no_ext'),  # 无扩展名的RAR分卷格式
            (r'\.(\d{3})$', '7z_volume'),  # 纯数字分卷（如 .001, .002）
            (r'\.(\d{2})$', 'generic'),
        ]

        for pattern, vtype in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                # 正确提取base_name，保留完整的基础名称，只移除分卷后缀
                base_name = re.sub(pattern, '', filename)
                logger.info(f"[VolumeSet] 检测到分卷模式: {filename}, base_name={base_name}, pattern={pattern}, vtype={vtype}")

                # 查找目录中所有匹配该基础名称和模式的文件
                volumes = self._find_all_volumes(directory, base_name, pattern)
                logger.info(f"[VolumeSet] 找到 {len(volumes)} 个分卷: {volumes}")

                # 对于 part 类型的分卷，必须有多个文件才算分卷组
                if vtype in ['part', 'part_no_ext'] and len(volumes) > 1:
                    return VolumeSet(base_name, volumes, vtype, entry_path=volumes[0])
                # 对于其他类型的分卷，也需要至少2个文件
                elif len(volumes) > 1:
                    return VolumeSet(base_name, volumes, vtype, entry_path=volumes[0])

        return None
    
    def _build_zip_volume_set(self, directory: str, base_name: str) -> Optional['VolumeSet']:
        zip_path = os.path.join(directory, f"{base_name}.zip")
        if not os.path.exists(zip_path):
            return None

        volumes: List[str] = []
        try:
            for file in os.listdir(directory):
                if re.fullmatch(rf'{re.escape(base_name)}\.z\d{{2}}', file, re.IGNORECASE):
                    volumes.append(os.path.join(directory, file))
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找 ZIP 分卷失败: {exc}")
            return None

        if not volumes:
            return None

        volumes.append(zip_path)
        ordered = sorted(volumes, key=self._volume_sort_key)
        return VolumeSet(base_name, ordered, 'zip_volume_main', entry_path=zip_path)

    def _build_rar_old_volume_set(self, directory: str, base_name: str) -> Optional['VolumeSet']:
        rar_path = os.path.join(directory, f"{base_name}.rar")
        if not os.path.exists(rar_path):
            return None

        volumes: List[str] = [rar_path]
        try:
            for file in os.listdir(directory):
                if re.fullmatch(rf'{re.escape(base_name)}\.r\d{{2}}', file, re.IGNORECASE):
                    volumes.append(os.path.join(directory, file))
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找旧式 RAR 分卷失败: {exc}")
            return None

        if len(volumes) <= 1:
            return None

        ordered = sorted(volumes, key=self._volume_sort_key)
        return VolumeSet(base_name, ordered, 'rar_volume_main', entry_path=rar_path)

    def _volume_sort_key(self, path: str):
        filename = os.path.basename(path).lower()

        part_match = re.search(r'\.part(\d+)(?:\.(?:rar|zip|7z|exe))?$', filename, re.IGNORECASE)
        if part_match:
            return (0, int(part_match.group(1)), filename)

        sevenzip_match = re.search(r'\.7z\.(\d{3})$', filename, re.IGNORECASE)
        if sevenzip_match:
            return (1, int(sevenzip_match.group(1)), filename)

        pure_numeric_match = re.search(r'\.(\d{3})$', filename, re.IGNORECASE)
        if pure_numeric_match:
            return (2, int(pure_numeric_match.group(1)), filename)

        zip_split_match = re.search(r'\.z(\d{2})$', filename, re.IGNORECASE)
        if zip_split_match:
            return (3, int(zip_split_match.group(1)), filename)

        rar_old_match = re.search(r'\.r(\d{2})$', filename, re.IGNORECASE)
        if rar_old_match:
            return (4, int(rar_old_match.group(1)), filename)

        if filename.endswith('.zip'):
            return (5, 0, filename)
        if filename.endswith('.rar'):
            return (5, 1, filename)

        two_digit_match = re.search(r'\.(\d{2})$', filename, re.IGNORECASE)
        if two_digit_match:
            return (6, int(two_digit_match.group(1)), filename)

        return (9, 0, filename)

    def _find_all_volumes(self, directory: str, base_name: str, pattern: str) -> List[str]:
        """查找所有分卷文件"""
        volumes = []
        logger.debug(f"[FindVolumes] directory={directory}, base_name={base_name}, pattern={pattern}")
        try:
            files = os.listdir(directory)
            logger.debug(f"[FindVolumes] 目录中的文件: {files}")
            for file in files:
                if file.startswith(base_name) and re.search(pattern, file, re.IGNORECASE):
                    volumes.append(os.path.join(directory, file))
                    logger.debug(f"[FindVolumes] 匹配到分卷: {file}")
        except Exception as e:
            logger.error(f"[FindVolumes] 列出目录失败: {e}")
        result = sorted(volumes, key=self._volume_sort_key)
        logger.info(f"[FindVolumes] 找到 {len(result)} 个分卷: {[os.path.basename(v) for v in result]}")
        return result
    
    async def _wait_for_complete_set(self, volume_set: 'VolumeSet', task: Optional[Task] = None, max_wait: int = 3600) -> bool:
        """等待分卷组完整"""
        start_time = asyncio.get_event_loop().time()
        check_interval = 5
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            # 检查任务是否被取消
            if task and task.is_cancelled():
                logger.info(f"任务在等待分卷组时被取消")
                return False
            
            # 检查任务是否暂停
            if task:
                await task.wait_if_paused()
            
            all_stable = True
            for volume in volume_set.volumes:
                if not os.path.exists(volume):
                    all_stable = False
                    break
                if not await self._is_file_stable_quick(volume):
                    all_stable = False
                    break
            
            if all_stable:
                return True
            
            await asyncio.sleep(check_interval)
        
        return False
    
    async def _is_file_stable_quick(self, file_path: str) -> bool:
        """快速检查文件是否稳定（只检查一次）"""
        try:
            size1 = os.path.getsize(file_path)
            await asyncio.sleep(2)
            size2 = os.path.getsize(file_path)
            return size1 == size2
        except OSError:
            return False
    
    def _build_filename_candidates(self, archive_path: str) -> List[str]:
        path_obj = Path(archive_path)
        filename = path_obj.name
        candidates: List[str] = []
        seen = set()

        def add_candidate(value: str):
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        add_candidate(filename)
        add_candidate(path_obj.stem)

        split_match = re.match(r'^(?P<base>.+\.7z)\.\d{3}$', filename, re.IGNORECASE)
        if split_match:
            add_candidate(split_match.group('base'))

        zip_split_match = re.match(r'^(?P<base>.+)\.z\d{2}$', filename, re.IGNORECASE)
        if zip_split_match:
            add_candidate(f"{zip_split_match.group('base')}.zip")

        rar_split_match = re.match(r'^(?P<base>.+)\.r\d{2}$', filename, re.IGNORECASE)
        if rar_split_match:
            add_candidate(f"{rar_split_match.group('base')}.rar")

        part_match = re.match(r'^(?P<base>.+)\.part\d+(?P<ext>\.(?:rar|zip|7z|exe))?$', filename, re.IGNORECASE)
        if part_match:
            ext = part_match.group('ext') or ''
            add_candidate(f"{part_match.group('base')}{ext}")

        return candidates

    async def _get_password_candidates_for_archive(self, archive_path: str) -> List[Dict[str, Optional[str]]]:
        """从密码库查找适合该压缩包的密码候选，并保留关联的 RJ 信息"""
        from ..models.database import PasswordEntry, get_db

        rjcodes = self._extract_rjcode_candidates(archive_path)
        filename_candidates = self._build_filename_candidates(archive_path)
        db = next(get_db())
        candidates: List[Dict[str, Optional[str]]] = []
        seen_passwords = set()
        dirty_entry_count = 0

        def add_entry(
            password: Optional[str],
            source: str,
            rjcode: Optional[str] = None,
            filename: Optional[str] = None,
            entry_id: Optional[str] = None,
        ):
            normalized_password = normalize_password_value(password)
            if not normalized_password:
                return
            if normalized_password in seen_passwords:
                return
            seen_passwords.add(normalized_password)
            normalized_rjcode = normalize_rjcode_value(rjcode)
            candidates.append({
                "entry_id": entry_id,
                "password": normalized_password,
                "source": source,
                "rjcode": normalized_rjcode,
                "filename": normalize_filename_value(filename),
            })

        try:
            if rjcodes:
                from sqlalchemy import func
                entries = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode).in_(rjcodes)).all()
                for entry in entries:
                    normalized_password = normalize_password_value(entry.password)
                    normalized_rjcode = normalize_rjcode_value(entry.rjcode)
                    normalized_filename = normalize_filename_value(entry.filename)
                    if (
                        normalized_password != str(entry.password or "")
                        or normalized_rjcode != entry.rjcode
                        or normalized_filename != entry.filename
                    ):
                        entry.password = normalized_password
                        entry.rjcode = normalized_rjcode
                        entry.filename = normalized_filename
                        dirty_entry_count += 1
                    add_entry(normalized_password, "密码库-RJ", normalized_rjcode, normalized_filename, entry.id)
                    logger.info(f"找到RJ号匹配的密码: {normalized_rjcode}")

            if filename_candidates:
                entries = db.query(PasswordEntry).filter(PasswordEntry.filename.in_(filename_candidates)).all()
                for entry in entries:
                    normalized_password = normalize_password_value(entry.password)
                    normalized_rjcode = normalize_rjcode_value(entry.rjcode)
                    normalized_filename = normalize_filename_value(entry.filename)
                    if (
                        normalized_password != str(entry.password or "")
                        or normalized_rjcode != entry.rjcode
                        or normalized_filename != entry.filename
                    ):
                        entry.password = normalized_password
                        entry.rjcode = normalized_rjcode
                        entry.filename = normalized_filename
                        dirty_entry_count += 1
                    add_entry(normalized_password, "密码库-文件名", normalized_rjcode, normalized_filename, entry.id)
                    logger.info(f"找到文件名匹配的密码: {normalized_filename}")

            generic_entries = db.query(PasswordEntry).filter(
                PasswordEntry.rjcode.is_(None),
                PasswordEntry.filename.is_(None)
            ).all()
            for entry in generic_entries:
                normalized_password = normalize_password_value(entry.password)
                if normalized_password != str(entry.password or ""):
                    entry.password = normalized_password
                    dirty_entry_count += 1
                add_entry(normalized_password, "密码库-通用", entry.rjcode, entry.filename, entry.id)

            if dirty_entry_count:
                db.commit()
                logger.info("已自动清洗 %s 条密码库脏数据", dirty_entry_count)

            return candidates
        finally:
            db.close()

    async def _get_passwords_for_archive(self, archive_path: str) -> List[str]:
        candidates = await self._get_password_candidates_for_archive(archive_path)
        return [item["password"] for item in candidates]

    def _looks_like_archive_entry(self, entry_name: str) -> bool:
        normalized = str(entry_name or "").strip().lower().replace("\\", "/")
        if not normalized:
            return False

        archive_suffixes = (
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
            ".tar.xz",
            ".txz",
            ".gz",
            ".bz2",
            ".xz",
        )
        if normalized.endswith(archive_suffixes):
            return True

        if re.search(r"\.(part\d+\.(rar|zip|7z)|7z\.\d{3}|z\d{2})$", normalized, re.IGNORECASE):
            return True

        return False

    def _extract_rjcode_candidates_from_text(self, text: str) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add_code(code: str):
            value = str(code or "").strip().upper()
            if value and value not in seen:
                seen.add(value)
                candidates.append(value)

        normalized_text = str(text or "")
        for match in re.finditer(r'[RVB]J\s*[-_.]?\s*(\d{6}|\d{8})(?!\d)', normalized_text, re.IGNORECASE):
            add_code(f"RJ{match.group(1)}")

        path_parts = re.split(r"[\\/]", normalized_text)
        for part in path_parts:
            part = str(part or "").strip()
            if not part:
                continue
            part_candidates = [part]
            stem = Path(part).stem
            if stem and stem != part:
                part_candidates.append(stem)
            for item in part_candidates:
                cleaned = re.sub(r'^\d+[._-]', '', item)
                number_match = re.fullmatch(r'(\d{6}|\d{8})', cleaned)
                if number_match:
                    add_code(f"RJ{number_match.group(1)}")

        return candidates

    def _extract_rjcode_candidates(self, archive_path: str) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add_code(code: str):
            code = code.upper()
            if code and code not in seen:
                seen.add(code)
                candidates.append(code)

        path_text = str(archive_path)
        for match in re.finditer(r'[RVB]J\s*[-_.]?\s*(\d{6}|\d{8})(?!\d)', path_text, re.IGNORECASE):
            digits = match.group(1)
            add_code(f"RJ{digits}")

        path_obj = Path(archive_path)
        parts = list(path_obj.parts)
        if path_obj.suffix:
            parts.append(path_obj.stem)
        for part in parts:
            cleaned = re.sub(r'^\d+[._-]', '', part)
            number_match = re.fullmatch(r'(\d{6}|\d{8})', cleaned)
            if number_match:
                add_code(f"RJ{number_match.group(1)}")

        return candidates

    async def infer_rjcode_from_archive(self, archive_path: str, max_nested_depth: int = 1) -> Optional[Dict[str, str]]:
        """在正式解压前，从压缩包目录和内层压缩包中尽力推断 RJ 号。"""
        seen_archives = set()
        return await self._infer_rjcode_from_archive_internal(
            archive_path=str(archive_path or ""),
            max_nested_depth=max(0, int(max_nested_depth)),
            current_depth=0,
            seen_archives=seen_archives,
        )

    def _find_archive_candidates_in_directory(self, directory: str, max_results: int = 8) -> List[str]:
        candidates: List[str] = []
        seen = set()
        root_dir = os.path.abspath(str(directory or ""))
        if not root_dir or not os.path.isdir(root_dir):
            return candidates

        for current_root, dirs, files in os.walk(root_dir):
            dirs.sort()
            files.sort()

            relative_root = os.path.relpath(current_root, root_dir)
            relative_root = "" if relative_root == "." else relative_root
            relative_root_posix = relative_root.replace("\\", "/")
            if relative_root_posix:
                root_candidates = self._extract_rjcode_candidates_from_text(relative_root_posix)
                if root_candidates:
                    return [f"dir::{relative_root_posix}::{root_candidates[0]}"]

            for filename in files:
                file_path = os.path.join(current_root, filename)
                relative_path = os.path.relpath(file_path, root_dir).replace("\\", "/")
                entry_candidates = self._extract_rjcode_candidates_from_text(relative_path)
                if entry_candidates:
                    return [f"path::{relative_path}::{entry_candidates[0]}"]

                is_archive_candidate = self._looks_like_archive_entry(filename)
                if not is_archive_candidate:
                    try:
                        is_archive_candidate = self._detect_by_magic_bytes(file_path) is not None
                    except Exception:
                        is_archive_candidate = False

                if is_archive_candidate and file_path not in seen:
                    seen.add(file_path)
                    candidates.append(file_path)
                    if len(candidates) >= max_results:
                        return candidates

        return candidates

    async def _infer_rjcode_from_archive_internal(
        self,
        archive_path: str,
        max_nested_depth: int,
        current_depth: int,
        seen_archives: set,
    ) -> Optional[Dict[str, str]]:
        normalized_archive_path = os.path.abspath(str(archive_path or ""))
        if not normalized_archive_path or normalized_archive_path in seen_archives:
            return None
        seen_archives.add(normalized_archive_path)

        direct_candidates = self._extract_rjcode_candidates(normalized_archive_path)
        if direct_candidates:
            result = {"rjcode": direct_candidates[0], "source": "archive_path"}
            logger.info(
                "[RJ 推断] 命中压缩包路径: archive=%s rjcode=%s depth=%s",
                normalized_archive_path,
                result["rjcode"],
                current_depth,
            )
            return result

        archive_info = await self._get_archive_info(normalized_archive_path)
        if not archive_info:
            logger.info(
                "[RJ 推断] 无法读取压缩包目录，终止本层预检: archive=%s depth=%s",
                normalized_archive_path,
                current_depth,
            )
            return None

        inferred_rjcode = str(getattr(archive_info, "inferred_rjcode", "") or "").strip().upper()
        if inferred_rjcode:
            result = {"rjcode": inferred_rjcode, "source": "password_entry"}
            logger.info(
                "[RJ 推断] 命中密码库关联: archive=%s rjcode=%s depth=%s",
                normalized_archive_path,
                result["rjcode"],
                current_depth,
            )
            return result

        nested_archive_entries: List[str] = []
        opaque_archive_entries: List[str] = []
        logger.info(
            "[RJ 推断] 开始扫描压缩包条目: archive=%s depth=%s total_entries=%s",
            normalized_archive_path,
            current_depth,
            len(archive_info.file_list or []),
        )
        for item in archive_info.file_list or []:
            entry_name = str((item or {}).get("name") or "").strip()
            if not entry_name:
                continue

            entry_candidates = self._extract_rjcode_candidates_from_text(entry_name)
            if entry_candidates:
                result = {"rjcode": entry_candidates[0], "source": f"archive_entry:{entry_name}"}
                logger.info(
                    "[RJ 推断] 命中压缩包条目: archive=%s entry=%s rjcode=%s depth=%s",
                    normalized_archive_path,
                    entry_name,
                    result["rjcode"],
                    current_depth,
                )
                return result

            if self._looks_like_archive_entry(entry_name):
                nested_archive_entries.append(entry_name)
            elif not bool((item or {}).get("is_dir")):
                entry_suffix = Path(entry_name).suffix.lower()
                entry_size = int((item or {}).get("size") or 0)
                if not entry_suffix and entry_size > 0:
                    opaque_archive_entries.append(entry_name)

        logger.info(
            "[RJ 推断] 条目扫描未直接命中: archive=%s depth=%s nested_candidates=%s opaque_candidates=%s",
            normalized_archive_path,
            current_depth,
            len(nested_archive_entries),
            len(opaque_archive_entries),
        )

        if current_depth >= max_nested_depth:
            logger.info(
                "[RJ 推断] 已达到最大嵌套深度，停止继续向内预检: archive=%s depth=%s max_depth=%s",
                normalized_archive_path,
                current_depth,
                max_nested_depth,
            )
            return None

        probe_entries = list(nested_archive_entries[:5])
        if not probe_entries:
            probe_entries.extend(opaque_archive_entries[:3])

        for entry_name in probe_entries:
            temp_dir = None
            try:
                logger.info(
                    "[RJ 推断] 开始探测内层条目: archive=%s entry=%s depth=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                )
                temp_dir = await self.extract_selected_entries(
                    normalized_archive_path,
                    [entry_name],
                )
                nested_archive_path = os.path.join(temp_dir, *str(entry_name).replace("\\", "/").split("/"))
                if not os.path.exists(nested_archive_path):
                    logger.debug(
                        "[RJ 推断] 内层压缩包条目提取后未找到文件: archive=%s entry=%s temp=%s",
                        normalized_archive_path,
                        entry_name,
                        temp_dir,
                    )

                extracted_tree_candidates = self._find_archive_candidates_in_directory(temp_dir)
                logger.info(
                    "[RJ 推断] 提取内层条目后扫描临时目录: archive=%s entry=%s depth=%s tree_candidates=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                    len(extracted_tree_candidates),
                )
                if extracted_tree_candidates:
                    first_candidate = extracted_tree_candidates[0]
                    if first_candidate.startswith("dir::"):
                        _, relative_dir, inferred_code = first_candidate.split("::", 2)
                        result = {
                            "rjcode": inferred_code,
                            "source": f"nested_directory:{entry_name}->{relative_dir}",
                        }
                        logger.info(
                            "[RJ 推断] 命中提取后的嵌套目录: archive=%s entry=%s relative_dir=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_dir,
                            inferred_code,
                            current_depth + 1,
                        )
                        return result
                    if first_candidate.startswith("path::"):
                        _, relative_path, inferred_code = first_candidate.split("::", 2)
                        result = {
                            "rjcode": inferred_code,
                            "source": f"nested_entry_path:{entry_name}->{relative_path}",
                        }
                        logger.info(
                            "[RJ 推断] 命中提取后的嵌套路径: archive=%s entry=%s relative_path=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_path,
                            inferred_code,
                            current_depth + 1,
                        )
                        return result

                candidate_archive_paths: List[str] = []
                if os.path.exists(nested_archive_path) and os.path.isfile(nested_archive_path):
                    candidate_archive_paths.append(nested_archive_path)
                for candidate_path in extracted_tree_candidates:
                    if candidate_path.startswith(("dir::", "path::")):
                        continue
                    if candidate_path not in candidate_archive_paths:
                        candidate_archive_paths.append(candidate_path)

                for candidate_archive_path in candidate_archive_paths[:5]:
                    nested_result = await self._infer_rjcode_from_archive_internal(
                        archive_path=candidate_archive_path,
                        max_nested_depth=max_nested_depth,
                        current_depth=current_depth + 1,
                        seen_archives=seen_archives,
                    )
                    if nested_result and nested_result.get("rjcode"):
                        nested_source = nested_result.get("source") or "nested_archive"
                        relative_candidate_path = os.path.relpath(candidate_archive_path, temp_dir).replace("\\", "/")
                        nested_result["source"] = f"nested_archive:{entry_name}->{relative_candidate_path}->{nested_source}"
                        logger.info(
                            "[RJ 推断] 命中内层压缩包: archive=%s entry=%s candidate=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_candidate_path,
                            nested_result["rjcode"],
                            current_depth + 1,
                        )
                        return nested_result
            except Exception as exc:
                logger.debug(
                    "[RJ 推断] 检查内层压缩包失败: archive=%s entry=%s depth=%s error=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                    exc,
                )
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)

        return None
    
    async def _record_password_usage(self, password: str, archive_path: str, entry_id: Optional[str] = None):
        """记录密码使用情况"""
        from ..models.database import PasswordEntry, get_db
        
        db = next(get_db())
        try:
            # 查找并更新使用记录
            entry = None
            if entry_id:
                entry = db.query(PasswordEntry).filter(PasswordEntry.id == entry_id).first()
            if not entry:
                normalized_password = normalize_password_value(password)
                entry = db.query(PasswordEntry).filter(PasswordEntry.password == normalized_password).first()
            if entry:
                # 使用 SQL 表达式更新，避免类型问题
                from sqlalchemy import func
                db.query(PasswordEntry).filter(PasswordEntry.id == entry.id).update({
                    'use_count': PasswordEntry.use_count + 1,
                    'last_used_at': func.now()
                })
                db.commit()
                logger.debug(f"记录密码使用: {entry.rjcode or entry.filename or '通用密码'}, 使用次数+1")
        except Exception as e:
            logger.warning(f"记录密码使用情况失败: {e}")
        finally:
            db.close()
    
    def _get_rj_passwords(self, archive_path: str) -> List[str]:
        """从压缩包路径提取RJ号并生成密码列表

        返回顺序: RJ号, RJ号+1, RJ号-1
        例如: 对于RJ123456，返回 ['RJ123456', 'RJ123457', 'RJ123455']
        """
        passwords = []
        seen = set()
        rjcodes = self._extract_rjcode_candidates(archive_path)
        for rjcode in rjcodes:
            digits = re.sub(r'^[RVB]J', '', rjcode, flags=re.IGNORECASE)
            if not digits.isdigit():
                continue
            width = len(digits)
            rj_number = int(digits)
            variants = [
                f"RJ{digits}",
                f"RJ{str(rj_number + 1).zfill(width)}",
                f"RJ{str(max(0, rj_number - 1)).zfill(width)}",
            ]
            for pwd in variants:
                if pwd not in seen:
                    seen.add(pwd)
                    passwords.append(pwd)
        if passwords:
            logger.debug(f"从路径提取RJ号生成密码: {passwords}")
        return passwords

    async def _get_archive_info(self, archive_path: str) -> Optional[ArchiveInfo]:
        """获取压缩包信息（文件列表、大小等）

        注意：这里只获取文件列表，不解压。真正能解压的密码在 _try_extract 中确定。
        为了不限制解压时的密码选择，这里尝试找一个能读取内容的密码即可。
        """
        password_candidates = await self._get_password_candidates_for_archive(archive_path)
        vault_passwords = [item["password"] for item in password_candidates]
        password_rjcode_map = {
            item["password"]: item.get("rjcode")
            for item in password_candidates
            if item.get("rjcode")
        }

        # 获取RJ号相关密码
        rj_passwords = self._get_rj_passwords(archive_path)

        # 构建密码列表：RJ号密码优先，然后密码库密码，最后是配置中的默认密码
        password_list = []
        password_list.extend(rj_passwords)  # RJ号密码（RJ号, RJ号+1, RJ号-1）
        password_list.extend(vault_passwords)  # 密码库密码
        password_list.append("")  # 无密码
        password_list.extend(self.config.extract.password_list)  # 默认密码
        
        # 去重（保持顺序）
        seen = set()
        unique_passwords = []
        for pwd in password_list:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)
        
        for password in unique_passwords:
            file_list = await self._list_archive_contents(archive_path, password)
            if file_list is not None:
                # 判断密码来源
                if password in rj_passwords:
                    source = "RJ号"
                elif password in vault_passwords:
                    source = "密码库"
                elif password in self.config.extract.password_list:
                    source = "默认"
                else:
                    source = "无"
                logger.info(f"成功读取压缩包内容，使用密码来源: {source} ({password or '无密码'})")
                # 注意：这里返回的 password 只是能读取内容的密码，不一定能解压
                # 真正能解压的密码会在 _try_extract 中更新
                return ArchiveInfo(
                    archive_path,
                    file_list,
                    password,
                    inferred_rjcode=password_rjcode_map.get(password),
                )

        logger.warning("无法预读取压缩包内容，后续将尝试直接解压: %s", archive_path)
        return None
    
    async def _list_archive_contents(self, archive_path: str, password: str = "") -> Optional[List[Dict]]:
        """列出压缩包内容，自动检测最佳编码"""
        password_args = [f'-p{password}'] if password else []
        commands = [
            [self.seven_zip, 'l', '-ba', *password_args, archive_path],
            [self.seven_zip, 'l', '-slt', *password_args, archive_path],
        ]

        for index, cmd in enumerate(commands):
            try:
                logger.debug(f"[7z] 执行命令: {' '.join(cmd)}")
                result = await self._run_7z_command(cmd)
                if result.returncode != 0:
                    logger.warning(
                        f"[7z] 列出压缩包内容失败，返回码: {result.returncode}, 错误: {result.stderr.decode('utf-8', errors='ignore')[:500]}"
                    )
                    continue

                raw_bytes = result.stdout
                best_encoding = self._detect_best_encoding(raw_bytes)
                logger.info(f"[7z] 自动检测编码: {best_encoding}")
                decoded = raw_bytes.decode(best_encoding, errors='ignore')
                file_list = (
                    self._parse_7z_list_output(decoded)
                    if index == 0
                    else self._parse_7z_technical_output(decoded)
                )
                if file_list:
                    return file_list
            except Exception as e:
                logger.error(f"列出压缩包内容失败: {e}")
        return None

    def _detect_best_encoding(self, raw_bytes: bytes) -> str:
        """
        自动检测压缩包文件名的最佳编码
        依次尝试: gbk -> shift_jis -> utf-8 -> big5 -> euc_kr
        """
        # 编码优先级列表（中文用户优先 GBK，日文次之）
        encodings = ['gbk', 'shift_jis', 'utf-8', 'big5', 'euc_kr']

        best_encoding = 'gbk'  # 默认
        best_score = -1

        for encoding in encodings:
            try:
                decoded = raw_bytes.decode(encoding, errors='replace')
                score = self._score_decoded_text(decoded)
                logger.debug(f"[编码检测] {encoding}: 得分 {score}")

                if score > best_score:
                    best_score = score
                    best_encoding = encoding
            except Exception as e:
                logger.debug(f"[编码检测] {encoding} 解码失败: {e}")
                continue

        return best_encoding

    def _score_decoded_text(self, text: str) -> int:
        """
        评估解码后文本的质量分数
        分数越高表示编码越可能是正确的
        """
        if not text:
            return 0

        score = 0

        # 1. 惩罚替换字符（乱码标志）
        replacement_count = text.count('\ufffd')
        score -= replacement_count * 10

        # 2. 惩罚控制字符（除换行、制表符外）
        control_chars = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
        score -= control_chars * 5

        # 3. 奖励常见字符（日文假名、中文、字母数字）
        for c in text:
            # 日文平假名、片假名
            if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff':
                score += 2
            # 中日韩统一表意文字
            elif '\u4e00' <= c <= '\u9fff':
                score += 1
            # 字母数字
            elif c.isalnum() or c in '._-+/\\':
                score += 1
            # 常见符号
            elif c in '（）()[]【】「」『』・·':
                score += 1
            # 空格
            elif c == ' ':
                score += 0.5

        # 4. 检测常见乱码模式（GBK解码Shift_JIS时出现的特征）
        # 例如：日文假名被错误解码成生僻汉字
        garbled_patterns = [
            r'[\u9e\u9f][\u00-\x7f]',  # 部分乱码特征
        ]
        for pattern in garbled_patterns:
            if re.search(pattern, text):
                score -= 20

        return int(score)
    
    def _parse_7z_list_output(self, output: str) -> List[Dict]:
        """解析7z列表输出"""
        files = []
        # 7z l -ba 输出格式: 日期 时间 属性 大小 压缩大小 文件名
        pattern = r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([D.][R.][H.][S.][A.])\s+(\d+)\s+(\d+)?\s+(.+)$'
        
        for line in output.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                size = int(match.group(4))
                name = match.group(6)
                files.append({
                    'name': name,
                    'size': size,
                    'is_dir': 'D' in match.group(3)
                })
        
        return files

    def _parse_7z_technical_output(self, output: str) -> List[Dict]:
        """解析 7z l -slt 输出，作为 -ba 失败时的兜底"""
        files: List[Dict] = []
        current: Dict[str, str] = {}

        def flush_current():
            if not current:
                return
            path_value = current.get('Path')
            size_value = current.get('Size')
            attr_value = current.get('Attributes', '')
            if path_value and size_value is not None:
                try:
                    files.append({
                        'name': path_value,
                        'size': int(size_value or 0),
                        'is_dir': 'D' in attr_value
                    })
                except ValueError:
                    pass

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                flush_current()
                current = {}
                continue
            if ' = ' not in line:
                continue
            key, value = line.split(' = ', 1)
            current[key.strip()] = value.strip()

        flush_current()
        return files
    
    async def _try_extract(
        self,
        archive_info: ArchiveInfo,
        output_path: str,
        task: Task,
        password_candidates: Optional[List[Dict[str, Optional[str]]]] = None,
    ) -> tuple[bool, Optional[str]]:
        """尝试解压，返回 (是否成功, 成功使用的密码)"""
        if password_candidates is None:
            password_candidates = await self._get_password_candidates_for_archive(archive_info.path)
        vault_passwords = [item["password"] for item in password_candidates]
        password_entry_id_map = {
            item["password"]: item.get("entry_id")
            for item in password_candidates
            if item.get("entry_id")
        }
        password_rjcode_map = {
            item["password"]: item.get("rjcode")
            for item in password_candidates
            if item.get("rjcode")
        }

        # 获取RJ号相关密码
        rj_passwords = self._get_rj_passwords(archive_info.path)

        # 构建密码列表：RJ号密码优先，然后密码库密码，已知密码，最后是默认密码
        password_list = []
        password_list.extend(rj_passwords)  # RJ号密码（RJ号, RJ号+1, RJ号-1）
        password_list.extend(vault_passwords)  # 密码库密码
        if archive_info.password and archive_info.password not in password_list:
            password_list.append(archive_info.password)
        password_list.append("")  # 无密码
        password_list.extend(self.config.extract.password_list)  # 默认密码
        
        # 去重（保持顺序）
        seen = set()
        unique_passwords = []
        for pwd in password_list:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)
        
        for password in unique_passwords:
            password_args = [f'-p{password}'] if password else []
            cmd = [
                self.seven_zip, 'x',
                '-y',  # 自动确认
                '-o' + output_path,  # 输出目录
                '-bsp1', # 启用进度输出
                '-bso1', # 将进度输出到 stdout
                *password_args,
                archive_info.path
            ]

            try:
                # 判断密码来源
                if password in rj_passwords:
                    password_source = "RJ号"
                elif password in vault_passwords:
                    password_source = "密码库"
                elif password == archive_info.password:
                    password_source = "已知"
                elif password == "":
                    password_source = "无"
                else:
                    password_source = "默认"
                
                # 创建进度解析回调
                start_time = datetime.now()
                last_update = 0

                def progress_callback(line: str):
                    nonlocal last_update
                    # 解析 7z 进度行，例如:  12% 123/1000 5678/100000000
                    percent_match = re.search(r"(\d{1,3})%", line)
                    if percent_match:
                        raw_percent = int(percent_match.group(1))
                        # 解压阶段占 10% - 95%
                        mapped = 10 + int(raw_percent * 0.85)
                        
                        now = datetime.now()
                        elapsed = (now - start_time).total_seconds()
                        
                        speed_str = ""
                        eta_str = ""
                        
                        # 提取已处理字节数以计算速度
                        # 7z 的进度行通常包含多个 x/y 部分，通常最后一个是字节
                        matches = re.findall(r"(\d+)/\d+", line)
                        if matches and elapsed > 0:
                            current_bytes = int(matches[-1])
                            speed = current_bytes / elapsed
                            if speed > 1024 * 1024:
                                speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
                            elif speed > 1024:
                                speed_str = f"{speed / 1024:.2f} KB/s"
                            else:
                                speed_str = f"{speed:.0f} B/s"
                            
                            if raw_percent > 0:
                                total_seconds = elapsed * 100 / raw_percent
                                remaining = total_seconds - elapsed
                                if remaining > 0:
                                    m, s = divmod(int(remaining), 60)
                                    h, m = divmod(m, 60)
                                    eta_str = f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

                        # 控制更新频率
                        current_ts = now.timestamp()
                        if current_ts - last_update >= 1 or raw_percent == 100:
                            last_update = current_ts
                            task.update_progress(min(99, mapped), f"解压中 {raw_percent}%" + (f" ({speed_str}, 剩余 {eta_str})" if speed_str else ""))

                task.update_progress(40, f"准备解压 (密码来源: {password_source})")
                result = await self._run_7z_command(cmd, progress_callback=progress_callback)
                
                if result.returncode == 0:
                    # 记录成功使用的密码
                    if password and password in vault_passwords:
                        await self._record_password_usage(
                            password,
                            archive_info.path,
                            entry_id=password_entry_id_map.get(password),
                        )
                    # 更新 archive_info 中的密码，用于传递给嵌套压缩包
                    archive_info.password = password
                    inferred_rjcode = password_rjcode_map.get(password)
                    if inferred_rjcode:
                        archive_info.inferred_rjcode = inferred_rjcode
                        task.task_metadata['inferred_rjcode'] = inferred_rjcode
                        task.task_metadata['rjcode'] = inferred_rjcode
                        task.task_metadata['inferred_rjcode_source'] = 'password_entry'
                        if not getattr(task, 'rjcode', None) or str(task.rjcode).strip() in {'', '未知'}:
                            task.rjcode = inferred_rjcode
                    logger.info(f"解压成功，使用{password_source}密码: {password or '无密码'}")
                    return True, password
                
            except Exception as e:
                logger.warning(f"解压尝试失败: {e}")
                continue
        
        return False, None
    
    async def _verify_extraction(self, archive_info: ArchiveInfo, output_path: str) -> bool:
        """验证解压完整性"""
        if not self.config.extract.verify_after_extract:
            return True

        if not archive_info.file_list:
            logger.warning("压缩包预读清单为空，跳过完整性验证: %s", archive_info.path)
            return True
        
        missing_files = []
        size_mismatch_files = []
        
        for expected in archive_info.file_list:
            if expected.get('is_dir'):
                continue
            
            # 尝试多种可能的路径（处理编码问题）
            possible_paths = [
                os.path.join(output_path, expected['name']),  # 原始路径
                os.path.join(output_path, expected['name'].encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')),  # UTF-8
                os.path.join(output_path, expected['name'].encode('cp932', errors='ignore').decode('cp932', errors='ignore')),  # Shift_JIS
            ]
            
            found = False
            for actual_path in set(possible_paths):  # 去重
                if os.path.exists(actual_path):
                    found = True
                    actual_size = os.path.getsize(actual_path)
                    if actual_size != expected['size']:
                        size_mismatch_files.append({
                            'name': expected['name'],
                            'expected': expected['size'],
                            'actual': actual_size
                        })
                    break
            
            if not found:
                missing_files.append(expected['name'])
        
        # 如果有文件缺失，记录警告但不失败（可能是编码问题）
        if missing_files:
            logger.warning(f"以下文件可能因编码问题无法验证: {missing_files[:5]}")
            if len(missing_files) > 5:
                logger.warning(f"... 还有 {len(missing_files) - 5} 个文件")
        
        if size_mismatch_files:
            for mismatch in size_mismatch_files[:5]:
                logger.warning(f"文件大小不匹配: {mismatch['name']} (期望: {mismatch['expected']}, 实际: {mismatch['actual']})")
        
        # 只要没有大小不匹配，就认为是成功的
        # （缺失文件可能是编码问题导致的误报）
        if size_mismatch_files:
            logger.error(f"有 {len(size_mismatch_files)} 个文件大小不匹配，解压可能不完整")
            return False
        
        return True
    
    async def _cleanup_extract_path(self, output_path: str):
        """异步清理解压路径，避免高并发失败时阻塞事件循环"""
        if not os.path.exists(output_path):
            return

        for attempt in range(3):
            try:
                await asyncio.to_thread(shutil.rmtree, output_path)
                logger.info(f"已清理解压目录: {output_path}")
                return
            except FileNotFoundError:
                return
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"清理尝试 {attempt + 1} 失败，1秒后重试: {output_path}")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"清理解压目录失败: {output_path}, {e}")
    
    async def _run_7z_command(self, cmd: List[str], progress_callback: Optional[Callable[[str], None]] = None) -> subprocess.CompletedProcess:
        """运行7z命令"""
        # 记录命令（显示密码用于调试）
        logger.info(f"执行7z命令: {' '.join(cmd)}")

        semaphore = self._get_7z_semaphore()

        try:
            async with semaphore:
                # Windows 上隐藏子进程窗口，避免闪烁
                kwargs = {
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.PIPE,
                    'stdin': subprocess.DEVNULL,
                }
                if sys.platform == 'win32':
                    from subprocess import CREATE_NO_WINDOW
                    kwargs['creationflags'] = CREATE_NO_WINDOW

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    **kwargs
                )

                stdout_data = bytearray()
                stderr_data = bytearray()

                async def read_stream(stream, buffer, is_stdout=False):
                    while True:
                        chunk = await stream.read(4096)
                        if not chunk:
                            break
                        buffer.extend(chunk)
                        if is_stdout and progress_callback:
                            try:
                                text = chunk.decode('utf-8', errors='ignore')
                                for line in text.replace('\r', '\n').split('\n'):
                                    if line.strip():
                                        progress_callback(line.strip())
                            except Exception:
                                pass

                await asyncio.gather(
                    read_stream(process.stdout, stdout_data, is_stdout=True),
                    read_stream(process.stderr, stderr_data)
                )

                return_code = await process.wait()
                await asyncio.sleep(0.1)

                if return_code != 0:
                    logger.error(f"7z命令执行失败，返回码: {return_code}")
                    try:
                        err_text = bytes(stderr_data).decode('gbk', errors='ignore')
                        logger.error(f"错误输出: {err_text[:200]}")
                    except Exception:
                        pass

                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=return_code,
                    stdout=bytes(stdout_data),
                    stderr=bytes(stderr_data)
                )
        except Exception as e:
            logger.error(f"执行7z命令异常: {e}")
            raise

class VolumeSet:
    """分卷组"""
    def __init__(self, base_name: str, volumes: List[str], volume_type: str, entry_path: Optional[str] = None):
        self.base_name = base_name
        self.volumes = volumes
        self.type = volume_type
        self.entry_path = entry_path or (volumes[0] if volumes else "")
        self.is_complete = False
