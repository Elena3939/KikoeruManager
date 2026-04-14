import os
import re
import shutil
import asyncio
from pathlib import Path
from pathlib import PurePosixPath
from typing import Optional, Dict
import logging

from ..config.settings import get_config, ClassificationRule
from ..models.database import LibrarySnapshot, ConflictWork, get_db
from ..core.task_engine import Task
from ..core.library_manager import get_library_manager
from ..core.folder_compare_service import get_folder_compare_service

logger = logging.getLogger(__name__)

class SmartClassifier:
    """智能分类器"""

    def __init__(self):
        # 不缓存配置，每次都获取最新配置
        pass

    @property
    def config(self):
        """动态获取最新配置"""
        return get_config()
    
    async def check_duplicate_before_extract(self, rjcode: str, task: Task, engine=None) -> bool:
        """
        在解压前检查是否重复（包括检查是否有其他任务正在处理）
        返回True表示存在重复或正在处理中，应该停止处理
        """
        logger.info(f"[预检] 开始检查RJ号 {rjcode} 是否已存在或正在处理")
        
        # 1. 检查是否已有其他任务正在处理这个RJ号
        if engine and engine.is_rjcode_processing(rjcode):
            logger.warning(f"[预检] RJ号 {rjcode} 正在被其他任务处理中，当前任务将等待")
            # 添加到问题作品表，标记为等待状态
            self._add_to_conflict_works(
                task.id, 
                rjcode, 
                'DUPLICATE', 
                "正在处理中", 
                task.source_path,
                {},
                status='PENDING'
            )
            return True
        
        # 2. 检查本地库中是否已存在
        logger.info(f"[预检] 检查本地库: {rjcode}")
        existing = self._check_existing(rjcode)
        
        if existing:
            # 强制使用DUPLICATE类型（预检阶段无法判断语言差异）
            conflict_type = 'DUPLICATE'
            
            logger.info(f"[预检] 本地库发现重复: RJ={rjcode}, 类型={conflict_type}, 已存在={existing['path']}")
            
            # 添加到问题作品表（不解压，只记录压缩包路径）
            self._add_to_conflict_works(
                task.id, 
                rjcode, 
                conflict_type, 
                existing['path'], 
                task.source_path,  # 压缩包路径
                {}  # 尚无元数据
            )
            
            logger.info(f"[预检] 已添加到问题列表等待手动处理")
            return True
        
        # 3. 检查远程 Kikoeru 服务器
        logger.info(f"[预检] 检查远程服务器: {rjcode}")
        kikoeru_result = await self._check_kikoeru_server(rjcode, task)
        if kikoeru_result:
            return True
        
        # 4. 标记RJ号正在处理（防止其他任务同时处理）
        if engine:
            engine.mark_rjcode_processing(rjcode)
            task.rjcode = rjcode  # 保存RJ号到任务，用于后续清理
        
        logger.info(f"[预检] 完成: RJ号 {rjcode} 未在本地库和远程服务器发现重复，继续解压")
        return False
    
    async def _check_kikoeru_server(self, rjcode: str, task: Task) -> bool:
        """
        检查远程 Kikoeru 服务器是否存在该作品
        
        Returns:
            bool: True 表示在远程服务器找到重复，应停止处理
        """
        try:
            config = get_config()
            
            # 检查是否启用远程查重
            if not hasattr(config, 'kikoeru_server'):
                return False
            
            kikoeru_config = config.kikoeru_server
            if not kikoeru_config.enabled:
                logger.debug(f"[Kikoeru预检] 远程查重未启用，跳过")
                return False
            
            # 检查是否在预检中启用
            if not getattr(kikoeru_config, 'check_in_preextract', True):
                logger.debug(f"[Kikoeru预检] 预检查重未启用，跳过")
                return False
            
            logger.info(f"[Kikoeru预检] 开始检查远程服务器: {rjcode}")
            
            from .kikoeru_duplicate_service import get_kikoeru_service
            service = get_kikoeru_service()
            
            # 重新加载配置以获取最新设置
            service.config = service._load_config()
            
            # 执行查重（包含关联作品检查）
            result = await service.check_duplicate_with_linkages(
                rjcode,
                cue_languages=['CHI_HANS', 'CHI_HANT', 'ENG'],
                use_cache=True
            )
            
            # 检查是否找到
            primary_result = result.get(rjcode)
            if primary_result and primary_result.is_found:
                logger.info(f"[Kikoeru预检] 在远程服务器找到作品: {rjcode} - {primary_result.title}")
                
                # 添加到问题作品表
                self._add_to_conflict_works(
                    task.id,
                    rjcode,
                    'DUPLICATE',
                    f"[远程服务器] {primary_result.title}",
                    task.source_path,
                    {
                        'work_name': primary_result.title,
                        'circle_name': primary_result.circle_name,
                        'source': 'kikoeru_server'
                    },
                    linked_works_info=[{
                        'rjcode': rjcode,
                        'title': primary_result.title,
                        'circle_name': primary_result.circle_name
                    }]
                )
                
                logger.info(f"[Kikoeru预检] 已添加到问题作品列表: {rjcode}")
                return True
            
            # 检查关联作品是否找到
            found_linked = [r for r, res in result.items() if res.is_found and r != rjcode]
            if found_linked:
                logger.info(f"[Kikoeru预检] 在远程服务器找到关联作品: {found_linked}")
                
                # 添加到问题作品表
                linked_info = [{
                    'rjcode': rj,
                    'title': result[rj].title,
                    'circle_name': result[rj].circle_name
                } for rj in found_linked]
                
                self._add_to_conflict_works(
                    task.id,
                    rjcode,
                    'DUPLICATE',
                    f"[远程服务器] 关联作品已存在: {', '.join(found_linked)}",
                    task.source_path,
                    {
                        'work_name': primary_result.title if primary_result else rjcode,
                        'source': 'kikoeru_server_linked'
                    },
                    linked_works_info=linked_info
                )
                
                logger.info(f"[Kikoeru预检] 因关联作品存在，已添加到问题作品列表: {rjcode}")
                return True
            
            logger.info(f"[Kikoeru预检] 远程服务器未找到: {rjcode}")
            return False
            
        except Exception as e:
            logger.error(f"[Kikoeru预检] 远程查重失败: {e}")
            # 查重失败不阻止处理，继续解压
            return False
    
    async def classify_and_move(self, source_path: str, metadata: Dict, task: Task) -> str:
        """
        智能分类并移动到库存
        返回最终路径
        """
        rjcode = metadata.get('rjcode', '')
        resolution = (task.task_metadata or {}).get('existing_folder_resolution') if getattr(task, 'task_metadata', None) else None
        resolution_existing_path = (task.task_metadata or {}).get('existing_path') if getattr(task, 'task_metadata', None) else None
        merge_decisions = (task.task_metadata or {}).get('merge_decisions') if getattr(task, 'task_metadata', None) else None
        
        # 1. 检查是否已存在
        task.update_progress(82, "检查重复")
        existing = self._check_existing(rjcode)
        manager = get_library_manager()
        target_library_id = task.task_metadata.get('target_library_id') if getattr(task, 'task_metadata', None) else None
        target_library = manager.get_library_definition(target_library_id)
        
        if existing and not (resolution in {"KEEP_NEW", "MERGE"} and resolution_existing_path and os.path.abspath(existing['path']) == os.path.abspath(str(resolution_existing_path))):
            # 使用DUPLICATE类型（解压后的重复检测，已有元数据但统一标记为重复）
            conflict_type = 'DUPLICATE'
            
            logger.info(f"解压后发现重复: RJ={rjcode}, 类型={conflict_type}, 已存在={existing['path']}")
            
            # 添加到问题作品表
            self._add_to_conflict_works(task.id, rjcode, conflict_type, existing['path'], source_path, metadata)
            
            # 等待用户处理（这里需要UI交互，简化处理）
            logger.info(f"发现重复作品: {rjcode}, 已添加到问题列表")
            # 临时移动到一个待处理目录
            # 使用重命名后的文件夹名称，而不是RJ号
            source_folder_name = os.path.basename(source_path)
            conflict_base_path = os.path.join(self.config.storage.library_path, '_conflicts')
            os.makedirs(conflict_base_path, exist_ok=True)
            final_path = self._move_with_rename(source_path, conflict_base_path)
            return final_path
        
        # 2. 应用分类规则（传入源路径以提取文件夹名中的社团名）
        task.update_progress(85, "应用分类规则")
        target_path = self._apply_classification_rules(metadata, source_path, target_library)

        # 3. 移动文件
        task.update_progress(90, "移动到库存")
        if resolution == "KEEP_NEW" and resolution_existing_path:
            task.update_progress(92, "替换现有目录")
            final_path = get_folder_compare_service().safe_replace_directory(source_path, str(resolution_existing_path))
        elif resolution == "MERGE" and resolution_existing_path:
            task.update_progress(92, "生成并写入合并结果")
            final_path = get_folder_compare_service().apply_merge(
                source_path,
                str(resolution_existing_path),
                merge_decisions or {},
                str(resolution_existing_path),
            )
        elif target_library.type == 'local':
            final_path = self._move_with_rename(source_path, target_path)
        else:
            relative_target_dir = os.path.relpath(target_path, target_library.root_path).replace("\\", "/")
            if relative_target_dir == '.':
                relative_target_dir = ''
            final_path = await manager.upload_directory_to_library(target_library.id, source_path, relative_target_dir)
            shutil.rmtree(source_path, ignore_errors=True)
        
        # 4. 更新库存快照
        self._update_library_snapshot(rjcode, final_path)
        
        return final_path
    
    def _check_existing(self, rjcode: str) -> Optional[Dict]:
        """检查作品是否已存在于库存"""
        logger.info(f"检查RJ号 {rjcode} 是否已存在于库存")

        def _is_valid_library_path(path: str) -> bool:
            normalized = os.path.abspath(str(path or "").strip())
            if not normalized or not os.path.exists(normalized):
                return False
            library_root = os.path.abspath(str(self.config.storage.library_path or "").strip())
            if library_root and not (normalized == library_root or normalized.startswith(library_root + os.sep)):
                return False
            invalid_markers = [
                f"{os.sep}_conflicts{os.sep}",
                f"{os.sep}待处理{os.sep}",
                f"{os.sep}temp{os.sep}",
                f"{os.sep}tmp{os.sep}",
            ]
            lowered = normalized.lower()
            if lowered.endswith(f"{os.sep}_conflicts") or lowered.endswith(f"{os.sep}待处理"):
                return False
            for marker in invalid_markers:
                if marker.lower() in lowered:
                    return False
            return True
        
        db = next(get_db())
        try:
            # 从数据库查询
            snapshot = db.query(LibrarySnapshot).filter(
                LibrarySnapshot.rjcode == rjcode
            ).first()

            # 验证数据库中的路径是否真实存在
            if snapshot:
                folder_path = str(snapshot.folder_path)
                logger.info(f"数据库中找到记录: {rjcode} -> {folder_path}")
                if _is_valid_library_path(folder_path):
                    logger.info(f"确认路径存在: {folder_path}")
                    return {
                        'path': folder_path,
                        'size': snapshot.folder_size
                    }
                else:
                    logger.warning(f"数据库记录无效，清理过期/临时记录: {rjcode} -> {folder_path}")
                    db.delete(snapshot)
                    db.commit()

            # 如果没有数据库记录，扫描库存目录
            library_path = Path(self.config.storage.library_path)
            logger.info(f"扫描库存目录: {library_path}")
            found_count = 0
            for folder in library_path.rglob('*'):
                if folder.is_dir() and rjcode in folder.name and _is_valid_library_path(str(folder)):
                    found_count += 1
                    logger.info(f"目录扫描找到已存在的作品: {rjcode} -> {folder}")
                    return {
                        'path': str(folder),
                        'size': self._get_folder_size(str(folder))
                    }
            
            logger.info(f"扫描完成，找到 {found_count} 个匹配项")
            return None
        except Exception as e:
            logger.error(f"检查作品存在性时出错: {e}")
            return None
        finally:
            db.close()
    
    def _determine_conflict_type(self, existing: Dict, new_metadata: Dict) -> str:
        """确定冲突类型"""
        existing_name = os.path.basename(existing['path']).lower()
        new_name = new_metadata.get('work_name', '').lower()
        
        # 检查是否是多语言版本
        if self._has_language_difference(existing_name, new_name):
            return 'LANGUAGE_VARIANT'
        
        # 检查是否是更新版本
        if existing['size'] != new_metadata.get('size', 0):
            return 'MULTIPLE_VERSIONS'
        
        return 'DUPLICATE'
    
    def _has_language_difference(self, name1: str, name2: str) -> bool:
        """检查是否有语言差异"""
        chinese_indicators = ['中文', '简体', '繁体', 'chinese', 'cn', 'tw']
        japanese_indicators = ['日文', 'japanese', 'jp']
        
        has_chinese_1 = any(ind in name1 for ind in chinese_indicators)
        has_chinese_2 = any(ind in name2 for ind in chinese_indicators)
        has_japanese_1 = any(ind in name1 for ind in japanese_indicators)
        has_japanese_2 = any(ind in name2 for ind in japanese_indicators)
        
        return has_chinese_1 != has_chinese_2 or has_japanese_1 != has_japanese_2
    
    def _add_to_conflict_works(self, task_id: str, rjcode: str, conflict_type: str,
                               existing_path: str, new_path: str, metadata: Dict,
                               status: str = 'PENDING', linked_works_info=None,
                               analysis_info=None, related_rjcodes=None):
        """添加到问题作品表（避免重复）"""
        import uuid
        from datetime import datetime
        
        db = next(get_db())
        try:
            pending_query = db.query(ConflictWork).filter(
                ConflictWork.status == 'PENDING'
            )

            # 失败问题项允许同一 RJ 下保留多条不同来源记录；
            # 否则会把后来的失败直接吞掉，任务中心里看得到失败，但问题作品页里没有。
            existing_conflict = None
            if new_path:
                existing_conflict = pending_query.filter(
                    ConflictWork.new_path == new_path
                ).first()

            if not existing_conflict and rjcode and conflict_type not in {'EXTRACT_FAILED', 'PROCESS_FAILED'}:
                existing_conflict = pending_query.filter(
                    ConflictWork.rjcode == rjcode,
                    ConflictWork.conflict_type == conflict_type,
                ).first()
            
            if existing_conflict:
                logger.info(f"冲突记录已存在，跳过重复添加: {rjcode}")
                return
            
            # 检查新文件是否还存在（如果用户已经手动删除了，就不需要再添加）
            if not os.path.exists(new_path):
                logger.info(f"新文件已不存在，跳过添加冲突记录: {rjcode}, 路径: {new_path}")
                return
            
            conflict = ConflictWork(
                id=str(uuid.uuid4()),
                task_id=task_id,
                rjcode=rjcode,
                conflict_type=conflict_type,
                existing_path=existing_path,
                new_path=new_path,
                new_metadata=metadata,
                status=status,
                linked_works_info=linked_works_info if linked_works_info is not None else [],
                analysis_info=analysis_info if analysis_info is not None else {},
                related_rjcodes=related_rjcodes if related_rjcodes is not None else [],
                created_at=datetime.now()
            )
            db.add(conflict)
            db.commit()
            logger.info(f"添加问题作品记录: {rjcode}")
        except Exception as e:
            logger.error(f"添加问题作品失败: {e}")
            db.rollback()
        finally:
            db.close()
    
    def _apply_classification_rules(self, metadata: Dict, source_path: str = None, target_library=None) -> str:
        """应用分类规则生成目标路径
        
        Args:
            metadata: 元数据字典
            source_path: 源文件夹路径（用于提取文件夹名中的社团名）
        """
        library_base = target_library.root_path if target_library is not None else self.config.storage.library_path
        
        for rule in self.config.classification:
            if not rule.enabled:
                continue
            
            path = self._apply_single_rule(rule, metadata, source_path)
            if path is not None:
                # path 可能是空字符串（表示无子目录）
                if path:
                    if target_library is not None and target_library.type != 'local':
                        return str(PurePosixPath(library_base) / path.replace("\\", "/"))
                    return os.path.join(library_base, path)
                else:
                    return library_base
        
        # 默认分类 - 直接放入库存根目录
        return library_base
    
    def _apply_single_rule(self, rule: ClassificationRule, metadata: Dict, source_path: str = None) -> Optional[str]:
        """应用单个分类规则，只返回分类目录（不包含作品文件夹名称）
        
        Args:
            rule: 分类规则
            metadata: 元数据字典
            source_path: 源文件夹路径（用于提取文件夹名中的社团名）
        """
        
        if rule.type == 'none':
            # 无子目录，直接返回空字符串表示根目录
            return ''
        
        elif rule.type == 'maker':
            maker_name = (
                metadata.get('classification_maker_name')
                or metadata.get('original_maker_name')
                or metadata.get('maker_name', '')
            )

            extracted_maker = None
            if source_path:
                folder_name = os.path.basename(source_path)
                extracted_maker = self._extract_maker_from_folder_name(folder_name)
                # 文件夹名已经是最终重命名结果时，优先使用 RJ 号前面的社团名。
                if extracted_maker and metadata.get('rjcode') and str(metadata.get('rjcode')).upper() in folder_name.upper():
                    if extracted_maker != maker_name:
                        logger.info(
                            "[分类] 使用文件夹名中的 RJ 前社团名覆盖分类社团名: metadata=%s folder=%s",
                            maker_name,
                            extracted_maker,
                        )
                    maker_name = extracted_maker
                elif not maker_name and extracted_maker:
                    logger.info(f"[分类] 元数据缺少社团名，回退使用文件夹名提取结果: {extracted_maker}")
                    maker_name = extracted_maker

            if not maker_name:
                return None
            
            # 使用自定义模板或默认使用社团名
            template = rule.path_template or '{maker_name}'
            # 只替换社团名
            path = template.replace('{maker_name}', self._sanitize_path(maker_name))
            return path
        
        elif rule.type == 'series':
            series_name = metadata.get('series_name')
            if not series_name:
                # 使用fallback规则
                if rule.fallback:
                    # 找到fallback规则并应用
                    for fallback_rule in self.config.classification:
                        if fallback_rule.type == rule.fallback:
                            return self._apply_single_rule(fallback_rule, metadata, source_path)
                return None
            
            # 使用自定义模板或默认使用系列名
            template = rule.path_template or '{series_name}'
            path = template.replace('{series_name}', self._sanitize_path(series_name))
            return path
        
        elif rule.type == 'rjcode':
            rjcode = metadata.get('rjcode', '')
            if not rjcode:
                return None
            
            # 检查RJ号是否在规则指定的范围内
            if rule.rjcode_range:
                try:
                    # 解析范围，格式如 "RJ01400000-RJ01499999"
                    range_parts = rule.rjcode_range.replace(' ', '').upper().split('-')
                    if len(range_parts) == 2:
                        start_rj = range_parts[0]
                        end_rj = range_parts[1]
                        # 提取数字部分进行比较
                        rj_num = int(''.join(filter(str.isdigit, rjcode)))
                        start_num = int(''.join(filter(str.isdigit, start_rj)))
                        end_num = int(''.join(filter(str.isdigit, end_rj)))
                        
                        if rj_num < start_num or rj_num > end_num:
                            return None  # RJ号不在范围内，跳过此规则
                except Exception as e:
                    logger.warning(f"RJ号范围解析失败: {rule.rjcode_range}, 错误: {e}")
                    # 解析失败时不阻止分类
            
            # 使用自定义目录名称
            if rule.custom_name:
                return rule.custom_name
            else:
                # 默认使用RJ号的前缀
                rj_prefix = rjcode[:5] if len(rjcode) >= 5 else rjcode
                return f"{rj_prefix}系列"
        
        elif rule.type == 'date':
            release_date = metadata.get('release_date', '')
            if not release_date:
                return None
            
            try:
                year = release_date[:4]
                month = release_date[5:7]
                template = rule.path_template or '{year}/{month}'
                path = template.replace('{year}', year)
                path = path.replace('{month}', month)
                return path
            except:
                return None
        
        return None
    
    def _sanitize_path(self, path: str) -> str:
        """清理路径中的非法字符"""
        # 移除Windows保留字符
        path = re.sub(r'[<>:"/\\|?*]', '', path)
        # 限制长度
        if len(path) > 100:
            path = path[:100]
        return path.strip()
    
    def _extract_maker_from_folder_name(self, folder_name: str) -> Optional[str]:
        """从文件夹名提取社团名
        
        支持格式：
        - [社团名][RJ123456]...
        - [社团名] 作品名...
        - 【社团名】作品名...
        
        Returns:
            社团名字符串，如果无法提取则返回 None
        """
        # 匹配开头的方括号或中文方括号内容
        # 格式：[社团名] 或 【社团名】
        pattern = r'^[【\[]([^\】\]]+)[】\]]'
        match = re.match(pattern, folder_name)
        
        if match:
            maker_name = match.group(1)
            # 排除 RJ 号（如果第一个方括号内是 RJ 号，则跳过）
            if re.match(r'^[RVB]J\d+$', maker_name, re.IGNORECASE):
                # 第一个方括号是 RJ 号，尝试匹配第二个方括号
                remaining = folder_name[match.end():]
                second_match = re.match(r'^[【\[]([^\】\]]+)[】\]]', remaining)
                if second_match:
                    potential_maker = second_match.group(1)
                    # 再次检查是否是 RJ 号
                    if not re.match(r'^[RVB]J\d+$', potential_maker, re.IGNORECASE):
                        logger.debug(f"[分类] 从第二个方括号提取社团名: {potential_maker}")
                        return potential_maker
                return None
            logger.debug(f"[分类] 从第一个方括号提取社团名: {maker_name}")
            return maker_name
        
        return None
    
    def _move_with_rename(self, source: str, target_dir: str) -> str:
        """移动文件/文件夹，处理重名"""
        source_path = Path(source)
        target_path = Path(target_dir)
        
        # 确保目标目录存在
        target_path.mkdir(parents=True, exist_ok=True)
        
        # 最终目标
        final_target = target_path / source_path.name
        
        # 如果源和目标相同，直接返回
        if final_target.exists() and final_target.resolve() == source_path.resolve():
            logger.info(f"移动: 源和目标相同，跳过: {final_target}")
            return str(final_target)
        
        # 处理重名 - 只有真正冲突时才添加后缀
        counter = 1
        original_target = final_target
        while final_target.exists() and final_target.resolve() != source_path.resolve():
            final_target = target_path / f"{original_target.stem}({counter}){original_target.suffix}"
            counter += 1
            if counter > 100:  # 防止无限循环
                logger.error(f"无法找到可用的目标路径，使用原路径")
                return source
            logger.info(f"移动: 目标已存在，尝试新名称: {final_target.name}")
        
        # 执行移动
        shutil.move(str(source_path), str(final_target))
        logger.info(f"移动: {source_path} -> {final_target}")
        
        return str(final_target)
    
    def _update_library_snapshot(self, rjcode: str, folder_path: str):
        """更新库存快照"""
        from datetime import datetime
        from .circle_completion_service import get_circle_completion_service
        
        db = next(get_db())
        try:
            # 删除旧记录
            db.query(LibrarySnapshot).filter(
                LibrarySnapshot.rjcode == rjcode
            ).delete()
            
            # 创建新记录
            folder_size = self._get_folder_size(folder_path)
            file_count = self._get_file_count(folder_path)
            
            snapshot = LibrarySnapshot(
                rjcode=rjcode,
                folder_path=folder_path,
                folder_size=folder_size,
                file_count=file_count,
                scanned_at=datetime.now()
            )
            db.add(snapshot)
            db.commit()
        except Exception as e:
            logger.error(f"更新库存快照失败: {e}")
            db.rollback()
        finally:
            db.close()

        try:
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            coroutine = get_circle_completion_service().sync_owned_for_rj(rjcode, folder_path=folder_path)
            if loop and loop.is_running():
                loop.create_task(coroutine)
            else:
                asyncio.run(coroutine)
        except Exception:
            logger.warning("更新社团补全拥有态索引失败: %s", rjcode, exc_info=True)
    
    def _get_folder_size(self, folder_path: str) -> int:
        """获取文件夹大小"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        return total_size
    
    def _get_file_count(self, folder_path: str) -> int:
        """获取文件数量"""
        count = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            count += len(filenames)
        return count
