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
from ..core.json_safety import database_safe_text, safe_json_value

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
        
        # 2. 只走 ready 库存索引。Kikoeru 只是播放这份库存的服务，不再作为拥有态
        # 查重源；索引未 ready / 未命中时直接继续，不主动扫盘、不请求群晖。
        local_result = await self._check_library_index_before_extract(rjcode, task)
        if local_result:
            return True
        
        # 3. 标记RJ号正在处理（防止其他任务同时处理）
        if engine:
            engine.mark_rjcode_processing(rjcode)
            task.rjcode = rjcode  # 保存RJ号到任务，用于后续清理
        
        logger.info(f"[预检] 完成: RJ号 {rjcode} 未在 ready 库存索引发现重复，继续解压")
        return False

    async def _check_library_index_before_extract(self, rjcode: str, task: Task) -> bool:
        """预解压优先用库存索引查当前 RJ 和关联 RJ。"""
        normalized_rj = str(rjcode or "").strip().upper()
        if not normalized_rj:
            return False

        manager = get_library_manager()

        try:
            direct_hits = manager.find_rj_in_ready_index([normalized_rj])
        except Exception:
            logger.warning("[预检] ready 库存索引查重失败 rj=%s", normalized_rj, exc_info=True)
            direct_hits = {}
        direct_match = next(iter(direct_hits.get(normalized_rj) or []), None)
        if direct_match:
            existing_path = str(direct_match.get("path") or "").strip()
            logger.info("[预检] 库存索引命中当前 RJ: %s -> %s", normalized_rj, existing_path)
            self._add_to_conflict_works(
                task.id,
                normalized_rj,
                "DUPLICATE",
                existing_path,
                task.source_path,
                {
                    "source": "library_index",
                    "existing_library_id": direct_match.get("library_id"),
                    "existing_library_name": direct_match.get("library_name"),
                    "existing_library_type": direct_match.get("library_type"),
                    "existing_size": direct_match.get("size"),
                },
                linked_works_info=[{
                    "rjcode": normalized_rj,
                    "path": existing_path,
                    "size": direct_match.get("size"),
                    "library_id": direct_match.get("library_id"),
                    "library_name": direct_match.get("library_name"),
                }],
                related_rjcodes=[normalized_rj],
            )
            return True

        linked_works = {}
        try:
            from .dlsite_service import get_dlsite_service
            linked_works = await get_dlsite_service().get_linked_works(normalized_rj)
        except Exception as exc:
            logger.info("[预检] 获取 DLsite 关联链失败，仅查当前 RJ: %s error=%s", normalized_rj, exc)

        related_rjcodes = [
            str(candidate or "").strip().upper()
            for candidate in (linked_works.keys() if linked_works else [])
            if str(candidate or "").strip().upper() and str(candidate or "").strip().upper() != normalized_rj
        ]

        try:
            linked_hits = manager.find_rj_in_ready_index(related_rjcodes)
        except Exception:
            logger.warning("[预检] ready 库存索引关联查重失败 rj=%s related=%s", normalized_rj, related_rjcodes, exc_info=True)
            linked_hits = {}

        for linked_rj in related_rjcodes:
            linked_match = next(iter(linked_hits.get(linked_rj) or []), None)
            if not linked_match:
                continue
            existing_path = str(linked_match.get("path") or "").strip()
            linked_work = linked_works.get(linked_rj) if linked_works else None
            work_type = str(getattr(linked_work, "work_type", "") or "")
            lang = str(getattr(linked_work, "lang", "") or "")
            if self._should_skip_linked_duplicate_for_subtitle_import(
                normalized_rj,
                linked_rj,
                linked_works,
                task,
            ):
                logger.info(
                    "[预检] 关联 RJ 命中原作但当前翻译作应进入字幕补配，跳过普通重复: "
                    "current=%s linked=%s path=%s",
                    normalized_rj,
                    linked_rj,
                    existing_path,
                )
                continue
            logger.info(
                "[预检] 库存索引命中关联 RJ: current=%s linked=%s path=%s",
                normalized_rj,
                linked_rj,
                existing_path,
            )
            self._add_to_conflict_works(
                task.id,
                normalized_rj,
                "DUPLICATE",
                existing_path,
                task.source_path,
                {
                    "work_name": normalized_rj,
                    "source": "library_index_linked",
                    "matched_rjcode": linked_rj,
                    "matched_work_type": work_type,
                    "matched_lang": lang,
                    "existing_library_id": linked_match.get("library_id"),
                    "existing_library_name": linked_match.get("library_name"),
                    "existing_library_type": linked_match.get("library_type"),
                    "existing_size": linked_match.get("size"),
                },
                linked_works_info=[{
                    "rjcode": linked_rj,
                    "work_type": work_type,
                    "lang": lang,
                    "path": existing_path,
                    "size": linked_match.get("size"),
                    "library_id": linked_match.get("library_id"),
                    "library_name": linked_match.get("library_name"),
                }],
                related_rjcodes=[normalized_rj, *related_rjcodes],
            )
            return True

        logger.info("[预检] 库存索引未命中当前 RJ / 关联 RJ: %s", normalized_rj)
        return False

    def _should_skip_linked_duplicate_for_subtitle_import(
        self,
        current_rjcode: str,
        linked_rjcode: str,
        linked_works: Dict,
        task: Task,
    ) -> bool:
        """翻译作补配原作字幕时，关联原作命中库存不算普通重复。"""
        metadata = dict(getattr(task, "task_metadata", None) or {})
        preview = dict(metadata.get("linked_subtitle_preview") or {})
        if not preview:
            return False
        if not bool(preview.get("is_translation_work")):
            return False
        if not bool(preview.get("target_needs_subtitle", preview.get("kikoeru_needs_subtitle"))):
            return False
        if bool(preview.get("kikoeru_target_is_empty_shell")):
            return False
        if not bool(
            preview.get("can_stage_pending")
            or preview.get("should_queue_pending")
            or preview.get("can_execute")
        ):
            return False

        normalized_current = str(current_rjcode or "").strip().upper()
        normalized_linked = str(linked_rjcode or "").strip().upper()
        preview_source = str(preview.get("source_rjcode") or "").strip().upper()
        preview_target = str(preview.get("target_rjcode") or "").strip().upper()
        if preview_source and preview_source != normalized_current:
            return False
        if preview_target and preview_target != normalized_linked:
            return False

        current_work = linked_works.get(normalized_current) if linked_works else None
        linked_work = linked_works.get(normalized_linked) if linked_works else None
        current_type = str(getattr(current_work, "work_type", "") or "").strip().lower()
        current_lang = str(getattr(current_work, "lang", "") or "").strip().upper()
        linked_type = str(getattr(linked_work, "work_type", "") or "").strip().lower()
        if current_type not in {"translation", "child_translation"}:
            return False
        if current_lang not in {"CHI_HANS", "CHI_HANT", "ENG"}:
            return False
        return linked_type == "original"
    
    async def _check_kikoeru_server(self, rjcode: str, task: Task) -> bool:
        """
        兼容旧入口：Kikoeru 不再作为拥有态查重源。
        
        Returns:
            bool: 固定 False，不阻止处理。
        """
        logger.info("[预检] Kikoeru 仅负责播放库存，跳过远程拥有态查重: %s", rjcode)
        return False
    
    def _notify_library_index_after_classify(
        self,
        manager,
        target_library,
        final_path: str,
        *,
        existing_path: Optional[str] = None,
    ) -> None:
        """落地完成后通知索引把新子树 upsert 进去。

        - target_library 为 None 或 final_path 在 _conflicts 下时跳过
        - KEEP_NEW / MERGE 替换原路径时，先 delete 旧子树再 upsert，避免孤儿条目
        - 任意异常都吞掉，不影响主流程返回 final_path
        """
        try:
            if not final_path or target_library is None:
                return
            normalized_final = str(final_path or "")
            if not normalized_final:
                return
            if target_library.type == 'local':
                conflict_root = os.path.abspath(
                    os.path.join(self.config.storage.library_path, '_conflicts')
                )
                normalized_abs = os.path.abspath(normalized_final)
                if (
                    normalized_abs == conflict_root
                    or normalized_abs.startswith(conflict_root + os.sep)
                ):
                    return  # _conflicts 不参与索引
            if existing_path and os.path.abspath(existing_path) == os.path.abspath(normalized_final):
                manager._enqueue_index_replace_subtree_many(target_library, [normalized_final])
                return
            if existing_path:
                manager._enqueue_index_delete_many(target_library, [existing_path])
            manager._enqueue_index_upsert_subtree_many(target_library, [normalized_final])
        except Exception:
            logger.debug(
                "[索引] classify 后通知索引 upsert 失败 path=%s", final_path, exc_info=True,
            )

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
        task.update_progress(82, "准备入库")
        task_type = getattr(task, 'type', None)
        task_type_value = getattr(task_type, 'value', task_type)
        skip_local_duplicate_check = task_type_value == 'auto_process'
        if skip_local_duplicate_check:
            logger.info(f"解压入库跳过本地库重复扫描: {rjcode}")
            existing = None
        else:
            task.update_progress(82, "检查重复")
            existing = self._check_existing(rjcode)
        manager = get_library_manager()
        target_library_id = task.task_metadata.get('target_library_id') if getattr(task, 'task_metadata', None) else None
        target_library = manager.get_library_definition(target_library_id)
        task.task_metadata = {
            **(task.task_metadata or {}),
            "target_library_id": target_library.id,
        }
        
        if existing and not (resolution in {"KEEP_NEW", "MERGE"} and resolution_existing_path and os.path.abspath(existing['path']) == os.path.abspath(str(resolution_existing_path))):
            # 使用DUPLICATE类型（解压后的重复检测，已有元数据但统一标记为重复）
            conflict_type = 'DUPLICATE'

            logger.info(f"解压后发现重复: RJ={rjcode}, 类型={conflict_type}, 已存在={existing['path']}")

            # 关键顺序：必须先把临时解压目录搬到 _conflicts/，再写问题作品记录。
            # 否则 conflict.new_path 会指向 /temp/RJxxx_subtask/...，
            # 这个临时目录会在任务结束 / 容器重启时被清掉，
            # 之后用户点"合并 / 保留新版"预览就会 404 New source does not exist。
            conflict_base_path = os.path.join(self.config.storage.library_path, '_conflicts')
            os.makedirs(conflict_base_path, exist_ok=True)
            final_path = await asyncio.to_thread(self._move_with_rename, source_path, conflict_base_path)

            # 用搬迁后的稳定路径写入 conflict 记录
            self._add_to_conflict_works(task.id, rjcode, conflict_type, existing['path'], final_path, metadata)

            logger.info(f"发现重复作品: {rjcode}, 已添加到问题列表，待处理路径: {final_path}")
            return final_path
        
        # 2. 应用分类规则（传入源路径以提取文件夹名中的社团名）
        task.update_progress(85, "应用分类规则")
        target_path = self._apply_classification_rules(metadata, source_path, target_library)

        # 3. 移动文件
        task.update_progress(90, "移动到库存")
        existing_subtree_to_clear: Optional[str] = None
        if resolution == "KEEP_NEW" and resolution_existing_path:
            task.update_progress(92, "替换现有目录")
            final_path = await asyncio.to_thread(
                get_folder_compare_service().safe_replace_directory,
                source_path,
                str(resolution_existing_path),
            )
            existing_subtree_to_clear = str(resolution_existing_path)
        elif resolution == "MERGE" and resolution_existing_path:
            task.update_progress(92, "生成并写入合并结果")
            final_path = await asyncio.to_thread(
                get_folder_compare_service().apply_merge,
                source_path,
                str(resolution_existing_path),
                merge_decisions or {},
                str(resolution_existing_path),
            )
            existing_subtree_to_clear = str(resolution_existing_path)
        elif target_library.type == 'local':
            # 跨卷复制时通过 progress 回调把"移动到库存"的真实进度映射到 90~94 区间。
            # 默认 shutil.move 在 NAS 跨卷场景下没有任何进度回报，前端经常停留在
            # 90%（"移动到库存"）十几分钟看不到任何变化；这里实时上报 MB 数。
            def _classify_move_progress(copied: int, total: int) -> None:
                try:
                    if total <= 0:
                        return
                    ratio = min(1.0, max(0.0, copied / total))
                    mb_done = copied / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    task.update_progress(
                        90 + int(ratio * 4),
                        f"移动到库存 {mb_done:.0f}/{mb_total:.0f}MB",
                    )
                except Exception:
                    logger.debug("classify 移动进度回调异常已忽略", exc_info=True)

            final_path = await asyncio.to_thread(
                self._move_with_rename,
                source_path,
                target_path,
                _classify_move_progress,
            )
        else:
            relative_target_dir = os.path.relpath(target_path, target_library.root_path).replace("\\", "/")
            if relative_target_dir == '.':
                relative_target_dir = ''
            final_path = await manager.upload_directory_to_library(
                target_library.id,
                source_path,
                relative_target_dir,
                delete_source_on_success=True,
            )
        
        # 4. 更新库存快照
        self._update_library_snapshot(rjcode, final_path)

        # 5. 通知索引把新子树扫进去（解压入库 / KEEP_NEW / MERGE / 远程上传共用通路）
        # 不在 classify_and_move 里 await：本地 upsert 同步即可（小子树 ms 级），
        # 远程 upsert 由 LibraryManager 自己起后台 task；这里只触发一下。
        self._notify_library_index_after_classify(
            manager,
            target_library,
            final_path,
            existing_path=existing_subtree_to_clear,
        )

        return final_path
    
    def _check_existing(self, rjcode: str) -> Optional[Dict]:
        """检查作品是否已存在于库存：只读 ready 库存索引，不扫盘。"""
        normalized_rj = str(rjcode or "").strip().upper()
        if not normalized_rj:
            return None
        try:
            hits = get_library_manager().find_rj_in_ready_index([normalized_rj])
        except Exception as e:
            logger.warning("[分类] ready 库存索引检查失败 rj=%s error=%s", normalized_rj, e, exc_info=True)
            return None
        hit = next(iter(hits.get(normalized_rj) or []), None)
        if not hit:
            logger.info("[分类] ready 库存索引未命中: %s", normalized_rj)
            return None
        logger.info("[分类] ready 库存索引命中: %s -> %s", normalized_rj, hit.get("path"))
        return {
            "path": str(hit.get("path") or ""),
            "size": int(hit.get("size") or 0),
            "file_count": int(hit.get("file_count") or 0),
            "library_id": str(hit.get("library_id") or ""),
            "library_name": str(hit.get("library_name") or ""),
        }
    
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
            active_query = db.query(ConflictWork).filter(
                ConflictWork.status.in_(['PENDING', 'PROCESSING'])
            )

            # 失败问题项允许同一 RJ 下保留多条不同来源记录；
            # 否则会把后来的失败直接吞掉，任务中心里看得到失败，但问题作品页里没有。
            existing_conflict = None
            if new_path:
                existing_conflict = active_query.filter(
                    ConflictWork.new_path == new_path
                ).first()

            if not existing_conflict and rjcode and conflict_type not in {'EXTRACT_FAILED', 'PROCESS_FAILED'}:
                existing_conflict = active_query.filter(
                    ConflictWork.rjcode == rjcode,
                    ConflictWork.conflict_type == conflict_type,
                ).first()
            
            if existing_conflict:
                logger.info(f"冲突记录已存在，跳过重复添加: {rjcode}")
                return
            
            # 检查新文件是否还存在（如果用户已经手动删除了，就不需要再添加）。
            # 解压/处理失败例外：临时输入可能已被上游清理，但失败事实仍要进问题作品页。
            if not os.path.exists(new_path) and conflict_type not in {'EXTRACT_FAILED', 'PROCESS_FAILED'}:
                logger.info(f"新文件已不存在，跳过添加冲突记录: {rjcode}, 路径: {new_path}")
                return
            # 注：以前这里还会再做一次 os.path.exists(new_path) 然后写
            # metadata['source_missing'] / 'source_missing_path' 字段。
            # 经全局 grep 确认这两个 key 在前后端 0 处读取（死字段），删除以省掉
            # EXTRACT_FAILED / PROCESS_FAILED 路径上的额外远程 stat 开销。
            safe_metadata = safe_json_value(metadata or {})
            safe_linked_works_info = safe_json_value(linked_works_info if linked_works_info is not None else [])
            safe_analysis_info = safe_json_value(analysis_info if analysis_info is not None else {})
            safe_related_rjcodes = safe_json_value(related_rjcodes if related_rjcodes is not None else [])
            safe_rjcode = database_safe_text(rjcode) if rjcode is not None else None
            safe_existing_path = database_safe_text(existing_path or "") or ""
            safe_new_path = database_safe_text(new_path or "") or ""

            conflict = ConflictWork(
                id=str(uuid.uuid4()),
                task_id=task_id,
                rjcode=safe_rjcode,
                conflict_type=conflict_type,
                existing_path=safe_existing_path,
                new_path=safe_new_path,
                new_metadata=safe_metadata if isinstance(safe_metadata, dict) else {},
                status=status,
                linked_works_info=safe_linked_works_info if isinstance(safe_linked_works_info, list) else [],
                analysis_info=safe_analysis_info if isinstance(safe_analysis_info, dict) else {},
                related_rjcodes=safe_related_rjcodes if isinstance(safe_related_rjcodes, list) else [],
                created_at=datetime.now()
            )
            db.add(conflict)
            db.commit()
            logger.info(f"添加问题作品记录: {rjcode}")
        except Exception as e:
            logger.error(f"添加问题作品失败: {e}", exc_info=True)
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
    
    def _move_with_rename(self, source: str, target_dir: str, progress_cb=None) -> str:
        """移动文件/文件夹，处理重名

        - 同卷直接 ``os.rename``，瞬间完成
        - 跨卷场景下走 fs_utils.move_path_efficient（8 MB buffer 流式），并把
          ``progress_cb(copied_bytes, total_bytes)`` 透传出去，方便上层把
          "移动到库存"的真实进度上报到任务中心
        """
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

        # 跨卷场景下走 efficient 流式 copy + 大 buffer。这里调用方 _move_with_rename
        # 是 sync 的（被 asyncio.to_thread 包装），所以用 asyncio.run 跑一次协程。
        from .fs_utils import move_path_efficient

        try:
            asyncio.run(
                move_path_efficient(
                    str(source_path),
                    str(final_target),
                    progress_cb=progress_cb,
                )
            )
        except RuntimeError:
            # asyncio.run 只能在没有运行 event loop 的线程里调用；
            # 极少数同步路径如果已经在 event loop 内被调用，回退到 shutil.move 老路径。
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
