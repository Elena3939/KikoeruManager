import os
import re
import shutil
from typing import Any, Optional
import logging

from ..config.settings import get_config
from ..core.task_engine import Task

logger = logging.getLogger(__name__)

class FilterService:
    """文件过滤服务"""

    def __init__(self):
        # 不缓存配置，每次都获取最新配置
        pass

    @property
    def config(self):
        """动态获取最新配置"""
        return get_config()
    
    async def filter(self, path: str, task: Task):
        """
        过滤文件和文件夹
        """
        if not self.config.filter.enabled:
            logger.info("过滤功能已禁用，跳过")
            return {
                "filtered_files": [],
                "filtered_dirs": [],
                "filtered_items": [],
                "filtered_count": 0,
                "filtered_size": 0,
            }
        
        task.update_progress(45, "过滤文件中")
        logger.info(f"开始过滤目录: {path}")
        
        # 如果没有配置规则，使用默认规则
        rules = self.config.filter.rules
        if not rules:
            logger.info("未配置过滤规则，使用默认规则")
            rules = [
                self._create_filter_rule("过滤无SE的WAV文件", r'(?:SE|音|音效)(?:[な無]し|CUT).*\.WAV$', target="file", action="exclude", enabled=True),
                self._create_filter_rule("过滤MP3文件", r'\.mp3$', target="file", action="exclude", enabled=False),
            ]
        
        # 检测音频格式分布，防止过滤后变成空文件夹
        audio_formats = self._detect_audio_formats(path)
        logger.info(f"检测到音频格式分布: {audio_formats}")
        
        # 如果只有 MP3 格式，临时禁用 MP3 过滤规则
        if audio_formats.get('mp3', 0) > 0 and len(audio_formats) == 1:
            logger.info("目录中只有 MP3 格式的音频文件，临时禁用 MP3 过滤规则以防止空文件夹")
            rules = self._disable_mp3_filter(rules)
        
        logger.info(f"当前过滤规则数: {len(rules)}")
        for i, rule in enumerate(rules):
            if hasattr(rule, 'target'):
                logger.info(f"规则 {i+1}: {rule.name}, target={rule.target}, pattern={rule.pattern}, enabled={rule.enabled}")
        
        filtered_files = []
        filtered_dirs = []
        filtered_items: list[dict[str, Any]] = []
        filtered_size = 0
        
        # 遍历目录
        for root, dirs, files in os.walk(path, topdown=False):
            # 过滤文件
            for file in files:
                file_path = os.path.join(root, file)
                if self._should_filter_file(file_path, rules):
                    size_bytes = 0
                    relative_path = ""
                    try:
                        size_bytes = int(os.path.getsize(file_path)) if os.path.exists(file_path) else 0
                    except Exception:
                        size_bytes = 0
                    try:
                        relative_path = os.path.relpath(file_path, path).replace("\\", "/")
                    except Exception:
                        relative_path = file
                    self._delete_file(file_path)
                    filtered_files.append(file)
                    filtered_size += size_bytes
                    filtered_items.append({
                        "path": file_path,
                        "relative_path": relative_path,
                        "name": file,
                        "type": "file",
                        "size": size_bytes,
                    })
                    logger.info(f"过滤文件: {file}")
            
            # 过滤文件夹
            if self.config.filter.filter_dir:
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    if self._should_filter_dir(dir_path, rules):
                        size_bytes = self._calculate_path_size(dir_path)
                        relative_path = ""
                        try:
                            relative_path = os.path.relpath(dir_path, path).replace("\\", "/")
                        except Exception:
                            relative_path = dir_name
                        self._delete_dir(dir_path)
                        filtered_dirs.append(dir_name)
                        filtered_size += size_bytes
                        filtered_items.append({
                            "path": dir_path,
                            "relative_path": relative_path,
                            "name": dir_name,
                            "type": "dir",
                            "size": size_bytes,
                        })
                        logger.info(f"过滤文件夹: {dir_name}")
        
        task.update_progress(50, f"过滤完成，已过滤 {len(filtered_files)} 个文件，{len(filtered_dirs)} 个文件夹")
        logger.info(f"过滤完成: 文件 {len(filtered_files)} 个，文件夹 {len(filtered_dirs)} 个")
        return {
            "filtered_files": filtered_files,
            "filtered_dirs": filtered_dirs,
            "filtered_items": filtered_items,
            "filtered_count": len(filtered_items),
            "filtered_size": int(filtered_size),
        }
    
    def _create_filter_rule(self, name: str, pattern: str, target: str = "file", action: str = "exclude", enabled: bool = True):
        """创建过滤规则对象"""
        class FilterRule:
            def __init__(self, name, pattern, target, action, enabled):
                self.name = name
                self.pattern = pattern
                self.target = target
                self.action = action
                self.enabled = enabled
        return FilterRule(name, pattern, target, action, enabled)

    def _should_filter_file(self, file_path: str, rules=None) -> bool:
        """判断是否应该过滤文件"""
        if rules is None:
            rules = self.config.filter.rules

        # 使用文件名而不是完整路径进行匹配
        file_name = os.path.basename(file_path)

        for rule in rules:
            if not rule.enabled:
                continue

            # 检查规则是否适用于文件
            if rule.target not in ['file', 'all']:
                continue

            try:
                match = re.search(rule.pattern, file_name, re.IGNORECASE)
                if match:
                    logger.debug(f"文件匹配规则: {file_name} -> {rule.name}")
                    return True  # 匹配到的就删除（简化逻辑）
            except re.error as e:
                logger.error(f"正则表达式错误: {rule.pattern}, {e}")

        return False
    
    def _should_filter_dir(self, dir_path: str, rules=None) -> bool:
        """判断是否应该过滤文件夹"""
        if rules is None:
            rules = self.config.filter.rules

        # 使用目录名而不是完整路径进行匹配
        dir_name = os.path.basename(dir_path)

        for rule in rules:
            if not rule.enabled:
                continue

            # 检查规则是否适用于文件夹
            if rule.target not in ['folder', 'all']:
                continue

            try:
                if re.search(rule.pattern, dir_name, re.IGNORECASE):
                    logger.debug(f"目录匹配规则: {dir_name} -> {rule.name}")
                    return True  # 匹配到的就删除（简化逻辑）
            except re.error as e:
                logger.error(f"正则表达式错误: {rule.pattern}, {e}")

        return False
    
    def _delete_file(self, file_path: str):
        """删除文件"""
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"删除文件失败: {file_path}, {e}")

    def _calculate_path_size(self, path: str) -> int:
        """计算文件或目录大小（字节）"""
        try:
            if not path or not os.path.exists(path):
                return 0
            if os.path.isfile(path):
                return int(os.path.getsize(path))
            total = 0
            for root, _, files in os.walk(path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total += int(os.path.getsize(file_path))
                    except Exception:
                        continue
            return int(total)
        except Exception:
            return 0
    
    def _delete_dir(self, dir_path: str):
        """删除文件夹"""
        try:
            shutil.rmtree(dir_path)
        except Exception as e:
            logger.error(f"删除文件夹失败: {dir_path}, {e}")
    
    def _detect_audio_formats(self, path: str) -> dict:
        """
        检测目录中的音频格式分布
        返回格式: {'wav': 10, 'mp3': 5, 'flac': 2}
        """
        audio_formats = {}
        audio_extensions = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac'}
        
        try:
            for root, dirs, files in os.walk(path):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in audio_extensions:
                        format_name = ext[1:]  # 去掉点号
                        audio_formats[format_name] = audio_formats.get(format_name, 0) + 1
        except Exception as e:
            logger.error(f"检测音频格式时出错: {e}")
        
        return audio_formats
    
    def _disable_mp3_filter(self, rules):
        """
        临时禁用 MP3 过滤规则
        创建规则的副本并禁用匹配 MP3 的规则
        """
        new_rules = []
        for rule in rules:
            # 创建规则的副本
            new_rule = self._create_filter_rule(
                name=rule.name,
                pattern=rule.pattern,
                target=rule.target,
                action=rule.action,
                enabled=rule.enabled
            )
            
            # 如果规则匹配 MP3，则禁用它
            if rule.enabled and rule.target in ['file', 'all']:
                if re.search(r'mp3', rule.pattern, re.IGNORECASE):
                    new_rule.enabled = False
                    logger.info(f"临时禁用 MP3 过滤规则: {rule.name}")
            
            new_rules.append(new_rule)
        
        return new_rules
