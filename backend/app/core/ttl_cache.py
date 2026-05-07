"""轻量 TTL + LRU 缓存。

设计目标：
- 群晖 docker 长期运行（不重启）下，避免裸 dict 缓存无界增长。
- 兼容大部分 dict-like 访问：``cache[k]`` / ``cache[k] = v`` / ``k in cache`` / ``cache.get`` / ``cache.pop`` / ``cache.update``。
- TTL：超过有效期的条目在 ``get`` / ``set`` 时被惰性清理；不依赖后台线程。
- LRU：超过 ``max_size`` 时按最久未访问顺序淘汰。
- 线程安全：内部 ``threading.Lock``，可在 asyncio + thread executor 混合场景使用。

注意：
- 与原生 dict 不同，``in`` / ``__getitem__`` / ``__contains__`` 都会更新 LRU 访问时间。
- ``items() / keys() / values()`` 返回当前未过期条目的快照，**不**反映后续修改。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Iterable, Iterator, Optional


class TTLCache:
    """LRU + TTL 双策略缓存（线程安全）。

    参数：
    - ``max_size``：最大条目数；超过后按 LRU 顺序剔除最久未访问条目。
    - ``ttl_seconds``：条目存活时间；``<=0`` 表示永不过期，仅 LRU 控制上限。
    - ``name``：日志 / 统计用的友好名称。
    """

    __slots__ = (
        "max_size",
        "ttl_seconds",
        "name",
        "_lock",
        "_store",
        "hits",
        "misses",
        "evictions",
    )

    def __init__(
        self,
        *,
        max_size: int = 1024,
        ttl_seconds: float = 0.0,
        name: str = "",
    ) -> None:
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.name = name or "ttl_cache"
        self._lock = threading.Lock()
        # value: (expires_at, payload)；expires_at == math.inf 表示永不过期
        self._store: "OrderedDict[Any, tuple[float, Any]]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    # ------------------- 内部工具 -------------------
    def _is_expired(self, expires_at: float) -> bool:
        return self.ttl_seconds > 0 and expires_at <= time.time()

    def _evict_if_needed_locked(self) -> None:
        if len(self._store) <= self.max_size:
            return
        # 1) 先批量清过期项（O(N) 一次扫描）
        if self.ttl_seconds > 0:
            now_ts = time.time()
            stale_keys = [k for k, (exp, _) in self._store.items() if exp <= now_ts]
            for k in stale_keys:
                self._store.pop(k, None)
                self.evictions += 1
        # 2) 还超就 LRU 淘汰
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)
            self.evictions += 1

    # ------------------- 主接口 -------------------
    def get(self, key, default: Any = None) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return default
            expires_at, value = entry
            if self._is_expired(expires_at):
                self._store.pop(key, None)
                self.misses += 1
                return default
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key, value) -> None:
        with self._lock:
            expires_at = time.time() + self.ttl_seconds if self.ttl_seconds > 0 else float("inf")
            if key in self._store:
                self._store[key] = (expires_at, value)
                self._store.move_to_end(key)
                return
            self._store[key] = (expires_at, value)
            self._evict_if_needed_locked()

    def pop(self, key, default: Any = None) -> Any:
        with self._lock:
            entry = self._store.pop(key, None)
            if entry is None:
                return default
            return entry[1]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def update(self, mapping) -> None:
        if not mapping:
            return
        items: Iterable
        if isinstance(mapping, dict):
            items = mapping.items()
        else:
            items = mapping
        for k, v in items:
            self.set(k, v)

    def keys(self) -> list:
        with self._lock:
            now_ts = time.time()
            return [k for k, (exp, _) in self._store.items() if self.ttl_seconds <= 0 or exp > now_ts]

    def items(self) -> list:
        with self._lock:
            now_ts = time.time()
            if self.ttl_seconds <= 0:
                return [(k, v) for k, (_, v) in self._store.items()]
            return [(k, v) for k, (exp, v) in self._store.items() if exp > now_ts]

    def values(self) -> list:
        return [v for _, v in self.items()]

    def invalidate_prefix(self, prefix: str) -> int:
        if not prefix:
            self.clear()
            return 0
        with self._lock:
            keys_to_drop = [k for k in self._store if isinstance(k, str) and k.startswith(prefix)]
            for k in keys_to_drop:
                self._store.pop(k, None)
            return len(keys_to_drop)

    def invalidate_predicate(self, predicate) -> int:
        """删除 predicate(key) 为 True 的全部条目。"""
        with self._lock:
            keys_to_drop = [k for k in self._store if predicate(k)]
            for k in keys_to_drop:
                self._store.pop(k, None)
            return len(keys_to_drop)

    def stats(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._store),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
            }

    # ------------------- dict-like 协议 -------------------
    def __getitem__(self, key) -> Any:
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value) -> None:
        self.set(key, value)

    def __delitem__(self, key) -> None:
        with self._lock:
            if key not in self._store:
                raise KeyError(key)
            self._store.pop(key, None)

    def __contains__(self, key) -> bool:
        # 直接走 get：会顺带触发过期清理 + LRU 更新
        sentinel = object()
        return self.get(key, sentinel) is not sentinel

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __iter__(self) -> Iterator:
        return iter(self.keys())

    def __repr__(self) -> str:
        return (
            f"TTLCache(name={self.name!r}, size={len(self)}/{self.max_size},"
            f" ttl={self.ttl_seconds}s, hits={self.hits}, misses={self.misses}, evictions={self.evictions})"
        )


__all__ = ["TTLCache"]
