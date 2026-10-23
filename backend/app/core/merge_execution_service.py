"""合并执行与 HTTP 连接解耦，刷新页面只重新订阅状态。"""
import asyncio
import time
import logging
from contextvars import ContextVar


merge_progress = ContextVar("merge_progress", default=None)
logger = logging.getLogger(__name__)


class MergeExecutionService:
    def __init__(self):
        self.jobs = {}
        self.workers = {}

    def submit(self, conflict_id, operation):
        current = self.jobs.get(conflict_id)
        if current and current["status"] in {"running", "completed"}:
            return dict(current)
        job = {"conflict_id": conflict_id, "status": "running", "message": "后台合并已开始", "percent": 0}
        self.jobs[conflict_id] = job
        self.workers[conflict_id] = asyncio.create_task(self._run(conflict_id, job, operation))
        return dict(job)

    async def _run(self, conflict_id, job, operation):
        def progress(message, percent):
            job.update(message=message, percent=percent)

        token = merge_progress.set(progress)
        try:
            logger.info("后台合并开始 conflict_id=%s", conflict_id)
            job["result"] = await operation()
            job.update(status="completed", message="合并完成", percent=100)
            logger.info("后台合并完成 conflict_id=%s", conflict_id)
        except Exception as exc:
            job.update(status="failed", error=str(getattr(exc, "detail", exc)), message="合并失败")
            logger.exception("后台合并失败 conflict_id=%s", conflict_id)
        finally:
            merge_progress.reset(token)
            job["finished_at"] = time.time()
            self.workers.pop(conflict_id, None)
            # 完成记录保留一天供刷新恢复，运行任务不按时间清除。
            for key, value in list(self.jobs.items()):
                if value.get("finished_at", time.time()) < time.time() - 86400:
                    self.jobs.pop(key, None)


merge_execution_service = MergeExecutionService()
