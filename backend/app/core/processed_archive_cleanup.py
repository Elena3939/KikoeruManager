"""
已处理压缩包智能清理服务
根据配置定期清理已处理的压缩包文件
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..config.settings import get_config
from ..models.database import ProcessedArchive, ProcessedArchiveCleanupLog, get_db

logger = logging.getLogger(__name__)


class ProcessedArchiveCleanupService:
    """已处理压缩包智能清理服务"""

    _instance = None
    _scheduler: Optional[AsyncIOScheduler] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._scheduler = None

    async def start(self):
        """启动清理服务"""
        config = get_config().processed_archive_cleanup

        if not config.enabled:
            logger.info("已处理压缩包智能清理服务已禁用")
            return

        if self._scheduler is not None:
            logger.warning("清理服务已经在运行")
            return

        try:
            self._scheduler = AsyncIOScheduler()

            # 添加定时任务
            self._scheduler.add_job(
                self._cleanup_job,
                trigger=CronTrigger.from_crontab(config.cron_expression),
                id="processed_archive_cleanup",
                name="已处理压缩包智能清理",
                replace_existing=True
            )

            self._scheduler.start()
            logger.info(f"已处理压缩包智能清理服务已启动，Cron表达式: {config.cron_expression}")
            logger.info(f"清理策略: {config.strategy}")

            # 记录下次执行时间
            next_run = self._scheduler.get_job("processed_archive_cleanup").next_run_time
            logger.info(f"下次清理时间: {next_run}")

        except Exception as e:
            logger.error(f"启动已处理压缩包清理服务失败: {e}")
            self._scheduler = None
            raise

    async def stop(self):
        """停止清理服务"""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("已处理压缩包智能清理服务已停止")

    async def restart(self):
        """重启清理服务（配置变更后调用）"""
        await self.stop()
        await self.start()

    async def _cleanup_job(self):
        """定时清理任务"""
        try:
            logger.info("开始执行已处理压缩包智能清理...")
            result = await self.cleanup_archives()
            logger.info(f"已处理压缩包清理完成: 删除了 {result['deleted_count']} 个文件，释放了 {result['freed_space_mb']:.2f} MB")
        except Exception as e:
            logger.error(f"已处理压缩包清理任务执行失败: {e}")

    async def cleanup_archives(self, dry_run: bool = False) -> dict:
        """
        执行压缩包清理

        Args:
            dry_run: 如果为True，只返回将要删除的压缩包列表而不实际删除

        Returns:
            dict: 包含 deleted_count、freed_space_mb、deleted_archives 等信息
        """
        config = get_config().processed_archive_cleanup

        if not config.enabled and not dry_run:
            return {
                "deleted_count": 0,
                "freed_space_mb": 0,
                "deleted_archives": [],
                "message": "清理服务已禁用"
            }

        # 归档队列在完成前可能已有一部分目标成员落到 processed 目录。任何
        # 队列状态不可读都必须使清理失败关闭，避免删掉恢复所依赖的唯一副本。
        try:
            from .deferred_archive_service import get_deferred_archive_service

            deferred_archive_service = get_deferred_archive_service()
            active_target_paths = await asyncio.to_thread(
                deferred_archive_service.active_target_paths_sync
            )
        except Exception:
            logger.warning("读取延后归档目标声明失败，跳过已处理压缩包清理", exc_info=True)
            return {
                "deleted_count": 0,
                "freed_space_mb": 0,
                "deleted_archives": [],
                "message": "延后归档队列状态不可读，已安全跳过清理",
            }

        def _normalized_path(path: str) -> str:
            return os.path.normcase(os.path.abspath(str(path or "")))

        def _physical_paths(archive: ProcessedArchive) -> list[str]:
            paths = [
                str((item or {}).get("target_path") or "").strip()
                for item in list(getattr(archive, "archive_manifest", None) or [])
                if str((item or {}).get("target_path") or "").strip()
            ]
            if not paths:
                current_path = str(getattr(archive, "current_path", "") or "").strip()
                paths = [current_path] if current_path else []
            return paths

        def _uses_active_target(archive: ProcessedArchive) -> bool:
            return any(_normalized_path(path) in active_target_paths for path in _physical_paths(archive))

        # === 阶段 A：短读事务 ===
        # 之前这里是一个跨循环长事务：循环里每删一个文件都 await asyncio.to_thread
        # 跑 os.remove，期间 SQLAlchemy session 把数据库事务连续持几分钟，
        # 阻塞所有其他写库接口。现在拆成"读 → 无 session 删文件 → 写"三段。
        archives_snapshot: List[dict] = []
        db = next(get_db())
        try:
            query = db.query(ProcessedArchive)
            if config.exclude_reprocessing:
                query = query.filter(ProcessedArchive.status != 'reprocessing')
            all_archives = [
                archive
                for archive in query.order_by(ProcessedArchive.processed_at.asc()).all()
                if not _uses_active_target(archive)
            ]

            archives_to_delete: List[ProcessedArchive] = []
            if config.strategy == 'age':
                cutoff_date = datetime.now() - timedelta(days=config.preserve_days)
                archives_to_delete = [
                    archive for archive in all_archives
                    if archive.processed_at and archive.processed_at <= cutoff_date
                ]
                logger.info(f"按时间清理策略: 处理时间 <= {cutoff_date.isoformat()}")
            elif config.strategy == 'count':
                if len(all_archives) > config.max_count:
                    archives_to_delete = all_archives[:-config.max_count]
                logger.info(f"按数量清理策略: 当前 {len(all_archives)} 个，保留 {config.max_count} 个")
            elif config.strategy == 'size':
                total_size = sum(archive.file_size or 0 for archive in all_archives)
                max_size_bytes = config.max_size_gb * 1024 * 1024 * 1024
                if total_size > max_size_bytes:
                    current_size = total_size
                    for archive in all_archives:
                        if current_size <= max_size_bytes:
                            break
                        archives_to_delete.append(archive)
                        current_size -= archive.file_size or 0
                logger.info(f"按容量清理策略: 当前 {total_size / (1024**3):.2f} GB，限制 {config.max_size_gb} GB")

            # 把 archive 关键字段拍成纯 dict，session 关闭后照样能用
            for archive in archives_to_delete:
                manifest = [
                    dict(item or {}) for item in list(getattr(archive, "archive_manifest", None) or [])
                ]
                archives_snapshot.append({
                    "id": archive.id,
                    "filename": archive.filename,
                    "rjcode": archive.rjcode,
                    "file_size": archive.file_size or 0,
                    "file_size_mb": (archive.file_size or 0) / (1024 * 1024),
                    "current_path": archive.current_path,
                    "archive_manifest": manifest,
                    "processed_at": archive.processed_at.isoformat() if archive.processed_at else None,
                    "process_count": archive.process_count,
                })
        finally:
            db.close()

        result = {
            "deleted_count": len(archives_snapshot),
            "freed_space_mb": sum(a["file_size"] for a in archives_snapshot) / (1024 * 1024),
            "deleted_archives": [
                {
                    "id": a["id"],
                    "filename": a["filename"],
                    "rjcode": a["rjcode"],
                    "file_size_mb": a["file_size_mb"],
                    "processed_at": a["processed_at"],
                    "process_count": a["process_count"],
                }
                for a in archives_snapshot
            ],
            "dry_run": dry_run,
            "config": {
                "strategy": config.strategy,
                "preserve_days": config.preserve_days if config.strategy == 'age' else None,
                "max_count": config.max_count if config.strategy == 'count' else None,
                "max_size_gb": config.max_size_gb if config.strategy == 'size' else None
            }
        }

        if not dry_run and archives_snapshot:
            # === 阶段 B：删物理文件（无 session，不占 db 连接 / 写锁） ===
            successfully_deleted_ids: List[str] = []
            freed_space = 0
            for snap in archives_snapshot:
                try:
                    physical_paths = [
                        str((item or {}).get("target_path") or "").strip()
                        for item in list(snap.get("archive_manifest") or [])
                        if str((item or {}).get("target_path") or "").strip()
                    ]
                    if not physical_paths:
                        physical_path = str(snap.get("current_path") or "").strip()
                        physical_paths = [physical_path] if physical_path else []
                    # 读取快照到实际删除之间可能恰好有新的归档作业预留同一路径。
                    # 再次按持久化队列核验，避免清理与恢复作业交错。
                    protected_by_queue = False
                    for physical_path in physical_paths:
                        if await asyncio.to_thread(
                            deferred_archive_service.is_target_claimed_sync,
                            physical_path,
                        ):
                            protected_by_queue = True
                            break
                    if protected_by_queue:
                        logger.info("跳过仍受延后归档队列保护的压缩包: %s", snap.get("filename"))
                        continue
                    for physical_path in physical_paths:
                        if os.path.exists(physical_path):
                            await asyncio.to_thread(os.remove, physical_path)
                            logger.debug(f"删除文件: {physical_path}")
                    successfully_deleted_ids.append(snap["id"])
                    freed_space += snap["file_size"]
                except Exception as e:
                    logger.warning(f"删除压缩包失败 {snap.get('filename')}: {e}")

            # === 阶段 C：短写事务批量删除 db 记录 + 写清理日志 ===
            if successfully_deleted_ids:
                write_db = next(get_db())
                try:
                    write_db.query(ProcessedArchive).filter(
                        ProcessedArchive.id.in_(successfully_deleted_ids)
                    ).delete(synchronize_session=False)
                    cleanup_log = ProcessedArchiveCleanupLog(
                        id=str(uuid.uuid4()),
                        deleted_count=len(successfully_deleted_ids),
                        freed_space_bytes=freed_space,
                        config_snapshot={
                            "strategy": config.strategy,
                            "preserve_days": config.preserve_days,
                            "max_count": config.max_count,
                            "max_size_gb": config.max_size_gb
                        },
                        deleted_archives_summary=[
                            {
                                "id": a["id"],
                                "filename": a["filename"],
                                "rjcode": a["rjcode"],
                                "file_size_mb": a["file_size_mb"]
                            }
                            for a in archives_snapshot
                            if a["id"] in set(successfully_deleted_ids)
                        ]
                    )
                    write_db.add(cleanup_log)
                    write_db.commit()
                except Exception as exc:
                    write_db.rollback()
                    logger.error(f"清理已处理压缩包时写库失败: {exc}")
                    raise
                finally:
                    write_db.close()

            result["deleted_count"] = len(successfully_deleted_ids)
            result["freed_space_mb"] = freed_space / (1024 * 1024)
            logger.info(f"已删除 {len(successfully_deleted_ids)} 个压缩包，释放 {result['freed_space_mb']:.2f} MB 空间")

        # 获取下次清理时间（不需要 session）
        if self._scheduler and self._scheduler.get_job("processed_archive_cleanup"):
            next_run = self._scheduler.get_job("processed_archive_cleanup").next_run_time
            result["next_cleanup_time"] = next_run.isoformat() if next_run else None
        else:
            result["next_cleanup_time"] = None

        return result

    async def get_cleanup_preview(self) -> dict:
        """获取清理预览（不实际删除）"""
        return await self.cleanup_archives(dry_run=True)

    async def get_cleanup_history(self, limit: int = 50) -> List[dict]:
        """获取清理历史记录"""
        db = next(get_db())
        try:
            logs = db.query(ProcessedArchiveCleanupLog).order_by(
                ProcessedArchiveCleanupLog.created_at.desc()
            ).limit(limit).all()

            return [
                {
                    "id": log.id,
                    "deleted_count": log.deleted_count,
                    "freed_space_mb": log.freed_space_bytes / (1024 * 1024) if log.freed_space_bytes else 0,
                    "config_snapshot": log.config_snapshot,
                    "deleted_archives_summary": log.deleted_archives_summary,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                for log in logs
            ]
        finally:
            db.close()

    def get_next_cleanup_time(self) -> Optional[datetime]:
        """获取下次清理时间"""
        if self._scheduler and self._scheduler.get_job("processed_archive_cleanup"):
            return self._scheduler.get_job("processed_archive_cleanup").next_run_time
        return None

    def is_running(self) -> bool:
        """检查服务是否正在运行"""
        return self._scheduler is not None and self._scheduler.running


# 全局服务实例
_cleanup_service: Optional[ProcessedArchiveCleanupService] = None


def get_processed_archive_cleanup_service() -> ProcessedArchiveCleanupService:
    """获取清理服务实例（单例）"""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = ProcessedArchiveCleanupService()
    return _cleanup_service


async def init_processed_archive_cleanup_service():
    """初始化并启动清理服务"""
    service = get_processed_archive_cleanup_service()
    await service.start()


async def shutdown_processed_archive_cleanup_service():
    """关闭清理服务"""
    service = get_processed_archive_cleanup_service()
    await service.stop()
