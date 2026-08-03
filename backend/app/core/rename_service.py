import asyncio
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

from ..config.settings import get_config
from ..core.task_engine import Task
from .ttl_cache import TTLCache

logger = logging.getLogger(__name__)

_TEMPLATE_FIELD_SPACE_RE = re.compile(r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000\u2423]+")


def normalize_template_maker_name(raw_value: str) -> str:
    """只规整空白；社团名里的标点和方括号必须原样保留。"""
    return _TEMPLATE_FIELD_SPACE_RE.sub(" ", str(raw_value or "")).strip()


class RenameService:
    """重命名服务"""

    def __init__(self):
        # 不缓存配置，每次都获取最新配置
        # 因为 save_config 会创建新的 AppConfig 对象
        # 原裸 dict 每个 RJ 永久驻留；TTL+LRU 限制上限，避免长期运行下内存持续增长
        self._japanese_metadata_cache: TTLCache = TTLCache(max_size=512, ttl_seconds=86400, name="rename.jp_metadata")

    @property
    def config(self):
        """动态获取最新配置"""
        return get_config()

    async def rename(self, path: str, task: Task):
        """
        重命名文件夹
        """
        metadata = task.task_metadata
        logger.info(f"重命名服务 - 原始路径: {path}")
        logger.info(f"重命名服务 - 任务元数据: {metadata}")

        if not metadata:
            raise Exception("缺少元数据，无法重命名")

        fallback_rjcode = str(
            metadata.get('rjcode')
            or metadata.get('inferred_rjcode')
            or getattr(task, 'rjcode', '')
            or ''
        ).strip().upper()
        if fallback_rjcode:
            metadata['rjcode'] = fallback_rjcode

        if not metadata.get('rjcode'):
            raise Exception(f"元数据中缺少RJ号，无法重命名。可用字段: {list(metadata.keys())}")

        task.update_progress(60, "重命名文件夹")

        # 如果启用了日语元数据，获取日语版本
        japanese_metadata = None
        if self.config.rename.use_japanese_metadata:
            task.update_progress(61, "获取日语元数据")
            japanese_metadata = await self._get_japanese_metadata(metadata.get('rjcode'))
            if japanese_metadata:
                japanese_maker_name = str(japanese_metadata.get('maker_name') or '').strip()
                if japanese_maker_name:
                    metadata['classification_maker_name'] = japanese_maker_name
                    metadata['original_maker_name'] = japanese_maker_name

        # 生成新名称
        new_name = self._compile_name(metadata, japanese_metadata)
        logger.info(f"重命名服务 - 生成的新名称: {new_name}")
        
        # 清理非法字符
        new_name = self._sanitize_filename(new_name)
        
        # 获取目标路径
        dir_path = Path(path)
        parent = dir_path.parent
        new_path = parent / new_name
        
        # 如果名称相同，跳过
        if dir_path.name == new_name:
            logger.info(f"重命名服务 - 名称相同，跳过重命名: {new_name}")
            return path
        
        # 处理重名 - 只有当目标路径与当前路径不同时才添加后缀
        if new_path.exists() and new_path != dir_path:
            # 检查是否是同一个文件夹（大小写不同的情况）
            if new_path.resolve() == dir_path.resolve():
                # 只是大小写不同，直接重命名
                pass
            else:
                # 真正的重名冲突，添加后缀
                logger.warning(f"重命名服务 - 发现同名文件夹: {new_path}，这可能导致重复")
                counter = 1
                original_new_path = new_path
                while new_path.exists() and new_path.resolve() != dir_path.resolve():
                    new_name_with_suffix = f"{original_new_path.name}({counter})"
                    new_path = parent / new_name_with_suffix
                    counter += 1
                    if counter > 100:  # 防止无限循环
                        logger.error(f"重命名服务 - 无法找到可用的名称，跳过重命名")
                        return path
                logger.info(f"重命名服务 - 使用新名称避免冲突: {new_path.name}")
        
        # 执行重命名
        await asyncio.to_thread(shutil.move, str(dir_path), str(new_path))
        logger.info(f"重命名: {dir_path} -> {new_path}")

        return str(new_path)

    async def _get_japanese_metadata(self, rjcode: str) -> Optional[dict]:
        """
        获取日语元数据（带缓存）

        Args:
            rjcode: RJ号

        Returns:
            日语元数据字典
        """
        # 检查缓存
        if rjcode in self._japanese_metadata_cache:
            return self._japanese_metadata_cache[rjcode]

        # 从 MetadataService 获取
        from .metadata_service import MetadataService
        metadata_service = MetadataService()

        japanese_metadata = await metadata_service.fetch_japanese_metadata(rjcode)

        # 缓存结果
        self._japanese_metadata_cache[rjcode] = japanese_metadata

        return japanese_metadata

    def _flatten_single_subfolder(
        self,
        path: str,
        operation_sink: Optional[list[dict[str, str]]] = None,
    ) -> str:
        """
        扁平化单一层级文件夹
        递归检查所有子文件夹，如果某个文件夹只有一个子文件夹（没有文件或其他内容），
        则将子文件夹内容移出。支持配置扁平化深度。
        """
        root_path = Path(path)
        max_depth = self.config.rename.flatten_depth

        def flatten_single_path(current_path: Path, current_depth: int) -> bool:
            """
            对单个路径进行扁平化，返回是否执行了扁平化
            current_depth: 当前已经扁平化的层数
            """
            if current_depth >= max_depth:
                return False

            if not current_path.is_dir():
                return False

            try:
                # 获取当前目录的所有内容
                items = list(current_path.iterdir())

                # 如果只有一个项目且是文件夹，则扁平化
                if len(items) == 1 and items[0].is_dir():
                    subfolder = items[0]
                    if operation_sink is not None:
                        try:
                            parent_relative = current_path.relative_to(root_path).as_posix()
                        except ValueError:
                            parent_relative = ""
                        operation_sink.append({
                            "parent_relative_path": "" if parent_relative == "." else parent_relative,
                            "removed_segment": subfolder.name,
                        })
                    logger.info(f"扁平化 (层 {current_depth + 1}/{max_depth}): {current_path.name} 只有一个子文件夹 {subfolder.name}，正在合并...")

                    # 创建临时路径
                    temp_path = current_path.parent / f"{current_path.name}_temp_{os.urandom(4).hex()}"

                    # 先将子文件夹移动到临时位置
                    shutil.move(str(subfolder), str(temp_path))

                    # 删除空的原文件夹
                    current_path.rmdir()

                    # 将临时文件夹重命名为原文件夹名
                    shutil.move(str(temp_path), str(current_path))

                    logger.info(f"扁平化完成 (层 {current_depth + 1}): {current_path}")

                    # 继续检查是否还需要扁平化（同一链条继续，深度+1）
                    flatten_single_path(current_path, current_depth + 1)
                    return True
                return False

            except Exception as e:
                logger.error(f"扁平化文件夹失败 {current_path}: {e}")
                return False

        def flatten_recursive(current_path: Path) -> None:
            """
            递归遍历所有文件夹，对每个文件夹尝试扁平化
            每个分支的扁平化深度独立计算
            """
            if not current_path.is_dir():
                return

            try:
                # 首先尝试扁平化当前路径（从深度0开始）
                flatten_single_path(current_path, 0)

                # 然后递归处理所有子文件夹
                items = list(current_path.iterdir())
                for item in items:
                    if item.is_dir():
                        flatten_recursive(item)

            except Exception as e:
                logger.error(f"递归扁平化失败 {current_path}: {e}")

        # 从根目录开始递归扁平化
        flatten_recursive(root_path)

        return str(root_path)

    def remove_empty_folders(self, path: str, remove_root: bool = False) -> None:
        """
        递归移除空文件夹
        :param path: 要处理的目录路径
        :param remove_root: 是否移除根目录（如果为空），默认为False保留根目录
        """
        if not os.path.isdir(path):
            return

        # 先递归处理子目录
        try:
            items = list(Path(path).iterdir())
        except Exception as e:
            logger.warning(f"无法读取目录内容 {path}: {e}")
            return

        for item in items:
            if item.is_dir():
                self.remove_empty_folders(str(item), remove_root=True)

        # 重新检查当前目录是否为空
        try:
            items = list(Path(path).iterdir())
            if len(items) == 0:
                if remove_root:
                    try:
                        Path(path).rmdir()
                        logger.info(f"移除空文件夹: {path}")
                    except Exception as e:
                        logger.warning(f"移除空文件夹失败 {path}: {e}")
        except Exception as e:
            logger.warning(f"检查空文件夹失败 {path}: {e}")
    
    def _compile_name(self, metadata: dict, japanese_metadata: Optional[dict] = None) -> str:
        """根据模板编译名称

        Args:
            metadata: 当前语言的元数据
            japanese_metadata: 日语元数据（可选），当启用 use_japanese_metadata 时使用
        """
        template = self.config.rename.template
        logger.info(f"[RENAME] 原始模板: '{template}' (长度: {len(template)})")

        # 确定用于填充模板的数据源
        # rjcode 和 work_name 始终使用当前语言的元数据
        # 其他字段在启用日语元数据时使用日语版本
        use_japanese = self.config.rename.use_japanese_metadata and japanese_metadata

        # 替换变量
        name = template

        # rjcode 和 work_name 始终使用当前语言版本
        rjcode = metadata.get('rjcode', '')
        work_name = metadata.get('work_name', '')

        logger.info(f"[RENAME] 替换前 - rjcode='{rjcode}', work_name='{work_name[:30] if len(work_name) > 30 else work_name}'")

        name = name.replace('{rjcode}', rjcode)
        logger.info(f"[RENAME] 替换rjcode后: '{name}'")

        name = name.replace('{work_name}', work_name)
        logger.info(f"[RENAME] 替换work_name后: '{name}'")

        # maker_id、原社团：日语元数据优先。旧 maker_name 模板继续映射到原社团。
        if use_japanese:
            maker_id = japanese_metadata.get('maker_id', metadata.get('maker_id', ''))
            original_maker_name = normalize_template_maker_name(
                japanese_metadata.get('original_maker_name')
                or japanese_metadata.get('maker_name')
                or metadata.get('original_maker_name')
                or metadata.get('maker_name', '')
            )
            logger.info(f"[RENAME] 使用日语元数据 - original_maker_name='{original_maker_name}'")
        else:
            maker_id = metadata.get('maker_id', '')
            original_maker_name = normalize_template_maker_name(
                metadata.get('original_maker_name')
                or metadata.get('maker_name', '')
            )
        translator_name = normalize_template_maker_name(
            metadata.get('translator_name', '')
        )

        name = name.replace('{maker_id}', maker_id)
        name = name.replace('{maker_name}', original_maker_name)
        name = name.replace('{original_maker_name}', original_maker_name)
        name = name.replace('{translator_name}', translator_name)

        # 日期：日语元数据优先
        if '{release_date}' in name:
            date_str = japanese_metadata.get('release_date', '') if use_japanese else metadata.get('release_date', '')
            if not date_str:
                date_str = metadata.get('release_date', '')
            if date_str:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    name = name.replace('{release_date}', date_obj.strftime(self.config.rename.date_format))
                except:
                    name = name.replace('{release_date}', '')
            else:
                name = name.replace('{release_date}', '')

        # CV列表：日语元数据优先
        if '{cvs}' in name:
            if use_japanese and japanese_metadata.get('cvs'):
                cvs = japanese_metadata.get('cvs', [])
                logger.info(f"[RENAME] 使用日语CV列表: {cvs[:3]}{'...' if len(cvs) > 3 else ''}")
            else:
                cvs = metadata.get('cvs', [])

            if cvs:
                cv_str = self.config.rename.delimiter.join(cvs)
                cv_str = f"{self.config.rename.cv_list_left}{cv_str}{self.config.rename.cv_list_right}"
                name = name.replace('{cvs}', cv_str)
            else:
                name = name.replace('{cvs}', '')

        # 标签列表：日语元数据优先
        if '{tags}' in name:
            if use_japanese and japanese_metadata.get('tags'):
                tags = japanese_metadata.get('tags', [])
                logger.info(f"[RENAME] 使用日语标签列表: {tags[:3]}{'...' if len(tags) > 3 else ''}")
            else:
                tags = metadata.get('tags', [])

            if tags:
                # 限制标签数量
                tags = tags[:self.config.rename.tags_max_number]
                tag_str = self.config.rename.delimiter.join(tags)
                name = name.replace('{tags}', tag_str)
            else:
                name = name.replace('{tags}', '')

        # 移除work_name中的方括号内容
        if self.config.rename.exclude_square_brackets:
            name = re.sub(r'【.*?】', '', name)

        return name.strip()
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        # Windows保留字符: < > : " / \ | ? *
        reserved_chars = r'[<>"/\\|?*]'
        
        if self.config.rename.illegal_char_to_full_width:
            # 转换为全角字符
            replace_map = {
                '<': '＜', '>': '＞', ':': '：', '"': '＂',
                '/': '／', '\\': '＼', '|': '｜', '?': '？', '*': '＊'
            }
            for char, replacement in replace_map.items():
                filename = filename.replace(char, replacement)
        else:
            # 直接移除
            filename = re.sub(reserved_chars, '', filename)
        
        # 移除首尾空格和点
        filename = filename.strip(' .')
        
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename
