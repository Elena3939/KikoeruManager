"""异常连接池退休管理；已有请求结束后再关闭，避免误伤并发请求。"""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger(__name__)


class HttpClientLifecycle:
    def __init__(self):
        self._active = {}
        self._retired = set()

    async def retire(self, client):
        self._retired.add(client)
        if not self._active.get(client, 0):
            try:
                await client.aclose()
            except Exception:
                logger.debug("关闭已退休 HTTP 连接池失败", exc_info=True)
            finally:
                self._retired.discard(client)

    @asynccontextmanager
    async def use(self, client, discard):
        self._active[client] = self._active.get(client, 0) + 1
        try:
            yield client
        except (httpx.TransportError, asyncio.CancelledError):
            # CONNECT 后 TLS 失败或取消时，底层池可能遗留 active 连接。
            # 立即从可复用入口移除，但等同池其它请求退出后才真正关闭。
            discard(client)
            self._retired.add(client)
            raise
        finally:
            remaining = self._active[client] - 1
            if remaining:
                self._active[client] = remaining
            else:
                self._active.pop(client, None)
                if client in self._retired:
                    await self.retire(client)
