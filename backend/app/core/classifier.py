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
        
        logger.info(f"[预检] 跳过本地库重复扫描，仅检查 Kikoeru: {rjcode}")

        # 2. 检查 Kikoeru 在线索引服务器（不是用户配置的远程库存）
        logger.info(f"[预检] 检查 Kikoeru 服务器: {rjcode}")
        kikoeru_result = await self._check_kikoeru_server(rjcode, task)
        if kikoeru_result:
            return True
        
        # 3. 标记RJ号正在处理（防止其他任务同时处理）
        if engine:
            engine.mark_rjcode_processing(rjcode)
            task.rjcode = rjcode  # 保存RJ号到任务，用于后续清理
        
        logger.info(f"[预检] 完成: RJ号 {rjcode} 未在 Kikoeru 发现重复，继续解压")
        return False
    
    async def _check_kikoeru_server(self, rjcode: str, task: Task) -> bool:
        """
        检查 Kikoeru 在线索引服务器是否存在该作品
        （注意：这里指的是 Kikoeru 在线 API 服务，不是用户配置的远程库存）
        
        Returns:
            bool: True 表示在 Kikoeru 服务器找到重复，应停止处理
        """
        try:
            config = get_config()
            
            # 检查是否启用远程查重
            if not hasattr(config, 'kikoeru_server'):
                return False
            
            kikoeru_config = config.kikoeru_server
            if not kikoeru_config.enabled:
                logger.debug(f"[Kikoeru预检] Kikoeru 查重未启用，跳过")
                return False
            
            # 检查是否在预检中启用
            if not getattr(kikoeru_config, 'check_in_preextract', True):
                logger.debug(f"[Kikoeru预检] 预检查重未启用，跳过")
                return False
            
            logger.info(f"[Kikoeru预检] 开始检查 Kikoeru 服务器: {rjcode}")
            
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

            # 读取 DLsite 关联信息，用于识别"当前是否翻译作品"。
            # 重复判定按以下三规则（与字幕补配预检保持一致）：
            #   - 规则 A：服务器拥有原作（无字幕）→ 翻译作走字幕补配；原作进重复。
            #   - 规则 B：服务器拥有原作（有字幕）→ 翻译作和原作都进重复。
            #   - 规则 C：服务器拥有任意翻译作 → 所有关联作品都进重复。
            linked_works = {}
            is_translation_work = False
            requested_lang = ""
            try:
                from .dlsite_service import get_dlsite_service
                linked_works = await get_dlsite_service().get_linked_works(rjcode)
                requested_work = linked_works.get(rjcode)
                requested_type = str(getattr(requested_work, 'work_type', '') or '').strip().lower()
                requested_lang = str(getattr(requested_work, 'lang', '') or '').strip().upper()
                is_translation_work = (
                    requested_type in {'translation', 'child_translation'}
                    and requested_lang in {'CHI_HANS', 'CHI_HANT', 'ENG'}
                )
            except Exception as e:
                logger.warning(f"[Kikoeru预检] 获取关联语言信息失败，回退通用判重: {rjcode}, error={e}")

            def _has_remote_subtitles(check_result) -> bool:
                subtitle_count = int(getattr(check_result, 'subtitle_file_count', 0) or 0)
                return subtitle_count > 0

            def _candidate_type(candidate_rj: str) -> str:
                linked = linked_works.get(candidate_rj)
                return str(getattr(linked, 'work_type', '') or '').strip().lower() if linked else ''

            # 检查是否找到
            primary_result = result.get(rjcode)

            if is_translation_work:
                # 收集服务器命中：任意翻译作（规则 C）+ 原作（规则 A/B）。
                # 注意：当前 RJ 自身命中也归入翻译命中，确保规则 C 兜底自身。
                translation_hits: list = []  # 含同语种 / 跨语种 / 当前 RJ 自身
                original_hit = None          # 原作命中（携带字幕状态）
                unknown_hits: list = []      # DLsite 未识别 work_type，但服务器命中

                for candidate_rj, candidate_result in result.items():
                    if not getattr(candidate_result, 'is_found', False):
                        continue
                    candidate_type = _candidate_type(candidate_rj)
                    if candidate_rj == rjcode or candidate_type in {'translation', 'child_translation'}:
                        translation_hits.append((candidate_rj, candidate_result))
                    elif candidate_type == 'original':
                        original_hit = (candidate_rj, candidate_result)
                    else:
                        # 由 related_translation 补查或 DLsite 未给 work_type 的命中：
                        # 服务端已按同语种过滤，这里也按"翻译命中"处理（规则 C）。
                        unknown_hits.append((candidate_rj, candidate_result))

                # 规则 C：服务器拥有翻译作（含当前 RJ 自身或任意关联翻译作） → 重复
                if translation_hits or unknown_hits:
                    all_translation_hits = translation_hits + unknown_hits
                    primary_match = next((item for item in all_translation_hits if item[0] == rjcode), None)
                    if primary_match:
                        _, hit = primary_match
                        current_subtitle_count = int(getattr(hit, 'subtitle_file_count', 0) or 0)
                        logger.info(
                            f"[Kikoeru预检] 当前翻译作品已在服务器: {rjcode} "
                            f"subtitle_count={current_subtitle_count}"
                        )
                        self._add_to_conflict_works(
                            task.id,
                            rjcode,
                            'DUPLICATE',
                            f"[Kikoeru 服务器] 当前翻译作品已存在: {hit.title}",
                            task.source_path,
                            {
                                'work_name': hit.title,
                                'circle_name': hit.circle_name,
                                'source': 'kikoeru_server',
                                'subtitle_file_count': current_subtitle_count,
                                'subtitle_check_source': str(getattr(hit, 'subtitle_check_source', '') or ''),
                            },
                            linked_works_info=[{
                                'rjcode': rjcode,
                                'title': hit.title,
                                'circle_name': hit.circle_name,
                                'subtitle_file_count': current_subtitle_count,
                            }]
                        )
                        return True

                    linked_hits = [
                        {
                            'rjcode': hit_rj,
                            'title': hit_res.title,
                            'circle_name': hit_res.circle_name,
                            'subtitle_file_count': int(getattr(hit_res, 'subtitle_file_count', 0) or 0),
                        }
                        for hit_rj, hit_res in all_translation_hits
                    ]
                    logger.info(
                        f"[Kikoeru预检] 服务器存在关联翻译作: {rjcode}, hits={linked_hits}"
                    )
                    self._add_to_conflict_works(
                        task.id,
                        rjcode,
                        'DUPLICATE',
                        f"[Kikoeru 服务器] 已存在翻译作品: {', '.join([h['rjcode'] for h in linked_hits])}",
                        task.source_path,
                        {
                            'work_name': rjcode,
                            'source': 'kikoeru_server_linked',
                            'requested_lang': requested_lang,
                        },
                        linked_works_info=linked_hits
                    )
                    return True

                # 规则 B：服务器拥有原作（有字幕） → 翻译作进重复
                if original_hit and _has_remote_subtitles(original_hit[1]):
                    original_rj, original_res = original_hit
                    original_subtitle_count = int(getattr(original_res, 'subtitle_file_count', 0) or 0)
                    logger.info(
                        f"[Kikoeru预检] 服务器原作已有字幕，翻译作按重复处理: "
                        f"current={rjcode} original={original_rj} subtitle_count={original_subtitle_count}"
                    )
                    self._add_to_conflict_works(
                        task.id,
                        rjcode,
                        'DUPLICATE',
                        f"[Kikoeru 服务器] 原作已有字幕，无需补配: {original_rj}",
                        task.source_path,
                        {
                            'work_name': original_res.title,
                            'circle_name': original_res.circle_name,
                            'source': 'kikoeru_server_linked',
                            'subtitle_file_count': original_subtitle_count,
                            'subtitle_check_source': str(getattr(original_res, 'subtitle_check_source', '') or ''),
                        },
                        linked_works_info=[{
                            'rjcode': original_rj,
                            'title': original_res.title,
                            'circle_name': original_res.circle_name,
                            'subtitle_file_count': original_subtitle_count,
                        }]
                    )
                    return True

                # 规则 A：服务器原作存在但无字幕 → 翻译作继续走字幕补配（不算重复）
                if original_hit:
                    logger.info(
                        f"[Kikoeru预检] 服务器原作存在但无字幕，翻译作继续后续字幕补配流程: "
                        f"current={rjcode} original={original_hit[0]}"
                    )
                    return False

                # 服务器既无原作也无翻译命中 → 不重复
                logger.info(
                    f"[Kikoeru预检] 翻译作品远程无任何关联命中，不判重复: {rjcode} "
                    f"(requested_lang={requested_lang or 'UNKNOWN'})"
                )
                return False

            # ── 当前是原作 / 非翻译作品的判定 ──
            # 规则 C / B / A 的原作分支：服务器拥有当前 RJ 或任意关联（含翻译作） → 重复
            if primary_result and primary_result.is_found:
                logger.info(f"[Kikoeru预检] 在 Kikoeru 服务器找到作品: {rjcode} - {primary_result.title}")

                self._add_to_conflict_works(
                    task.id,
                    rjcode,
                    'DUPLICATE',
                    f"[Kikoeru 服务器] {primary_result.title}",
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

            # 关联作品（任意原作 / 翻译作）命中 → 当前是原作时一律按重复处理
            found_linked = [r for r, res in result.items() if res.is_found and r != rjcode]
            if found_linked:
                logger.info(f"[Kikoeru预检] 在 Kikoeru 服务器找到关联作品: {found_linked}")

                linked_info = [{
                    'rjcode': rj,
                    'title': result[rj].title,
                    'circle_name': result[rj].circle_name,
                    'subtitle_file_count': int(getattr(result[rj], 'subtitle_file_count', 0) or 0),
                } for rj in found_linked]

                self._add_to_conflict_works(
                    task.id,
                    rjcode,
                    'DUPLICATE',
                    f"[Kikoeru 服务器] 关联作品已存在: {', '.join(found_linked)}",
                    task.source_path,
                    {
                        'work_name': primary_result.title if primary_result else rjcode,
                        'source': 'kikoeru_server_linked'
                    },
                    linked_works_info=linked_info
                )
                logger.info(f"[Kikoeru预检] 因关联作品存在，已添加到问题作品列表: {rjcode}")
                return True

            logger.info(f"[Kikoeru预检] Kikoeru 服务器未找到: {rjcode}")
            return False
            
        except Exception as e:
            logger.error(f"[Kikoeru预检] Kikoeru 查重失败: {e}")
            # 查重失败不阻止处理，继续解压
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
            if existing_path and os.path.abspath(existing_path) != os.path.abspath(normalized_final):
                # KEEP_NEW / MERGE 的 final 路径跟 existing 不同 → 旧路径条目要清掉
                manager._notify_index_self_mutation_delete(target_library, existing_path)
            elif existing_path:
                # final == existing：先把旧子树清掉，等下面 upsert 重新写一遍，避免孤儿
                manager._notify_index_self_mutation_delete(target_library, existing_path)
            manager._notify_index_self_mutation_upsert_subtree(target_library, normalized_final)
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
            final_path = get_folder_compare_service().safe_replace_directory(source_path, str(resolution_existing_path))
            existing_subtree_to_clear = str(resolution_existing_path)
        elif resolution == "MERGE" and resolution_existing_path:
            task.update_progress(92, "生成并写入合并结果")
            final_path = get_folder_compare_service().apply_merge(
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

            # 如果没有数据库记录，两层扫描：社团层 → 作品层（避免全盘 rglob）
            library_path = Path(self.config.storage.library_path)
            logger.info(f"两层扫描库存目录: {library_path}")
            try:
                for maker_dir in library_path.iterdir():
                    if not maker_dir.is_dir():
                        continue
                    # 社团层本身就含 RJ 号（非标准归档，少见）
                    if rjcode in maker_dir.name and _is_valid_library_path(str(maker_dir)):
                        logger.info(f"目录扫描找到已存在的作品(社团层): {rjcode} -> {maker_dir}")
                        return {
                            'path': str(maker_dir),
                            'size': self._get_folder_size(str(maker_dir))
                        }
                    # 扫描社团目录下一层（作品层）
                    try:
                        for work_dir in maker_dir.iterdir():
                            if work_dir.is_dir() and rjcode in work_dir.name and _is_valid_library_path(str(work_dir)):
                                logger.info(f"目录扫描找到已存在的作品: {rjcode} -> {work_dir}")
                                return {
                                    'path': str(work_dir),
                                    'size': self._get_folder_size(str(work_dir))
                                }
                    except (PermissionError, OSError):
                        continue
            except (PermissionError, OSError) as e:
                logger.warning(f"扫描库存目录失败: {e}")
            logger.info(f"两层扫描完成，未找到 {rjcode}")
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
            
            # 检查新文件是否还存在（如果用户已经手动删除了，就不需要再添加）。
            # 解压/处理失败例外：临时输入可能已被上游清理，但失败事实仍要进问题作品页。
            if not os.path.exists(new_path) and conflict_type not in {'EXTRACT_FAILED', 'PROCESS_FAILED'}:
                logger.info(f"新文件已不存在，跳过添加冲突记录: {rjcode}, 路径: {new_path}")
                return
            # 注：以前这里还会再做一次 os.path.exists(new_path) 然后写
            # metadata['source_missing'] / 'source_missing_path' 字段。
            # 经全局 grep 确认这两个 key 在前后端 0 处读取（死字段），删除以省掉
            # EXTRACT_FAILED / PROCESS_FAILED 路径上的额外远程 stat 开销。

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
