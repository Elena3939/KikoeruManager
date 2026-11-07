"""持久特典封面队列：网络异常保留未知，稳定结论事务内触发局部更新。"""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, update

from ..models.database import SessionLocal, CircleCompletionCoverFact as Cover, get_local_now

logger = logging.getLogger(__name__)


class CircleCompletionCoverWorker:
    def __init__(self, sessions=SessionLocal, image_cache=None):
        self.sessions = sessions
        self.image_cache = image_cache
        self.task = None

    def claim(self):
        now = get_local_now()
        with self.sessions.begin() as db:
            rows = db.scalars(select(Cover).where(Cover.pending.is_(True),
                (Cover.checked_at.is_(None)) | (Cover.checked_at < now - timedelta(minutes=5)))
                .order_by(Cover.checked_at.asc().nullsfirst(), Cover.rjcode)
                .with_for_update(skip_locked=True).limit(4)).all()
            codes = [row.rjcode for row in rows]
            for row in rows:
                row.checked_at = now
            return codes, now

    def finish(self, code, claimed_at, statuses):
        card, thumb = statuses
        conclusion = ("available" if "available" in statuses else
                      "missing" if card == thumb == "missing" else "unknown")
        with self.sessions.begin() as db:
            return db.execute(update(Cover).where(Cover.rjcode == code, Cover.checked_at == claimed_at)
                .values(card_status=card, list_status=thumb, conclusion=conclusion,
                        pending=conclusion == "unknown")).rowcount

    async def probe(self, code, claimed_at):
        from .circle_image_cache_service import get_circle_image_cache_service
        cache = self.image_cache or get_circle_image_cache_service()
        try:
            # 领取后的网络工作必须在下一次租约领取之前结束。
            async with asyncio.timeout(120):
                await cache.ensure_local_for_filename(f"{code}.jpg", log_failure=False)
                await cache.ensure_local_for_filename(f"{code}_sam.jpg", log_failure=False)
            def statuses():
                return tuple("available" if cache.has_local(code, variant=variant) else
                    "missing" if cache.has_known_missing(code, variant=variant) else "unknown"
                    for variant in ("card", "list"))
            await asyncio.to_thread(self.finish, code, claimed_at, await asyncio.to_thread(statuses))
        except Exception:
            # pending 留在 PG，进程退出、超时和暂时网络错误都可重新领取。
            logger.warning("[社团物化] 特典封面稍后重试 rjcode=%s", code, exc_info=True)

    async def run_once(self):
        codes, claimed_at = await asyncio.to_thread(self.claim)
        await asyncio.gather(*(self.probe(code, claimed_at) for code in codes))
        return bool(codes)

    async def _run(self):
        while True:
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("[社团物化] 封面队列失败")
                worked = False
            await asyncio.sleep(0.1 if worked else 2)

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="circle-cover-facts")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


_worker = CircleCompletionCoverWorker()


def get_circle_completion_cover_worker():
    return _worker
