"""
操作记录异步写入器（Phase 1）。

设计目标：
- 让 write_activity_log 从同步 commit 变成入队 + 批量 flush，避免任务 finally 被 SQLite
  writer lock 拖慢。
- 另提供一个 lifecycle 执行器，把 log_task_lifecycle_event 里昂贵的磁盘扫描
  （os.walk / ProcessedArchive 回查）挪出任务关键路径。
- 单例 + 守护线程；进程退出时调 shutdown() 做 flush。
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


_SENTINEL = object()
_DEFAULT_BATCH_SIZE = 64
_DEFAULT_FLUSH_INTERVAL = 0.2  # 秒；200ms 足够把高频小批量聚合成一次提交


class ActivityLogWriter:
    """带队列的批量写入器。

    使用方式：
        writer = get_activity_log_writer()
        writer.enqueue({...})   # 非阻塞
        writer.shutdown()       # 进程退出前调用

    语义注意：
    - 入队即视为"尽力写入"，未提供 at-least-once 的更强保证；flush 失败仅记告警日志。
    - 批量失败会自动降级为逐条重试，尽量保留其它记录。
    """

    def __init__(
        self,
        *,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self._queue: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self._last_write_ts: float = 0.0
        self._batch_size = max(1, int(batch_size))
        self._flush_interval = max(0.02, float(flush_interval))

    # ---- 生命周期 ----
    def _ensure_thread(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopped.clear()
            thread = threading.Thread(
                target=self._run,
                name="activity-log-writer",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stopped.set()
        self._queue.put(_SENTINEL)
        self._thread.join(timeout=timeout)
        self._thread = None

    def flush_sync(self, timeout: float = 5.0) -> None:
        """阻塞等待当前队列写完（测试 / shutdown 辅助用）。"""
        deadline = time.monotonic() + timeout
        while self._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.02)

    # ---- 入队 ----
    def enqueue(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        self._queue.put(payload)
        self._ensure_thread()

    @property
    def last_write_ts(self) -> float:
        """最近一次成功批提交的墙钟时间（time.time()）。用于列表/统计缓存失效。"""
        return self._last_write_ts

    # ---- 内部 ----
    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                first = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if first is _SENTINEL:
                return

            batch: list[Dict[str, Any]] = [first]
            deadline = time.monotonic() + self._flush_interval
            while len(batch) < self._batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if item is _SENTINEL:
                    self._flush(batch)
                    return
                batch.append(item)
            self._flush(batch)

        # 收尾：stop 被置位后，把队列里残留的继续写
        drained: list[Dict[str, Any]] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                continue
            drained.append(item)
            if len(drained) >= self._batch_size:
                self._flush(drained)
                drained = []
        if drained:
            self._flush(drained)

    def _flush(self, batch: list[Dict[str, Any]]) -> None:
        if not batch:
            return
        # 延迟导入避免循环依赖
        from ..models.database import ActivityLog, SessionLocal
        from .activity_log_rollup_service import get_activity_log_rollup_service
        from .resource_budget_service import get_resource_budget_service

        db = SessionLocal()
        try:
            with get_resource_budget_service().acquire_sync("sqlite_write", reason="activity_log.flush"):
                db.bulk_save_objects([ActivityLog(**payload) for payload in batch])
                self._upsert_daily_stats(db, batch)
                get_activity_log_rollup_service().upsert_from_payloads(db, batch)
                db.commit()
            self._last_write_ts = time.time()
            return
        except Exception:
            db.rollback()
            logger.warning("[操作记录] 批量写入失败，降级为逐条重试", exc_info=True)
        finally:
            db.close()

        # 降级：逐条单独提交，尽量保留更多记录
        for payload in batch:
            try:
                db2 = SessionLocal()
                try:
                    with get_resource_budget_service().acquire_sync("sqlite_write", reason="activity_log.flush_one"):
                        db2.add(ActivityLog(**payload))
                        self._upsert_daily_stats(db2, [payload])
                        get_activity_log_rollup_service().upsert_from_payloads(db2, [payload])
                        db2.commit()
                    self._last_write_ts = time.time()
                except Exception:
                    db2.rollback()
                    logger.warning("[操作记录] 单条写入失败: category=%s action=%s", payload.get("category"), payload.get("action"), exc_info=True)
                finally:
                    db2.close()
            except Exception:
                logger.warning("[操作记录] 单条写入打开会话失败", exc_info=True)

    @staticmethod
    def _upsert_daily_stats(db, batch: list[Dict[str, Any]]) -> None:
        """Phase 4A：批量聚合后 UPSERT 到 activity_log_daily_stats。

        - 在 batch 里先按 (date, category, status) 本地累加，避免给同一格子发多条 UPSERT；
        - 用 SQLite 原生 `INSERT ... ON CONFLICT(...) DO UPDATE` 做原子累加；
        - 任何失败都只告警，不影响主表写入（主表已经 bulk_save_objects 成功）。
        """
        from datetime import datetime as _dt
        from sqlalchemy import text as _text

        counters: Dict[tuple, int] = {}
        for payload in batch:
            created_at = payload.get("created_at")
            if isinstance(created_at, _dt):
                date_str = created_at.strftime("%Y-%m-%d")
            elif isinstance(created_at, str) and len(created_at) >= 10:
                date_str = created_at[:10]
            else:
                date_str = _dt.now().strftime("%Y-%m-%d")
            category = (payload.get("category") or "")[:40]
            status = (payload.get("status") or "")[:20]
            key = (date_str, category, status)
            counters[key] = counters.get(key, 0) + 1

        if not counters:
            return

        stmt = _text(
            """
            INSERT INTO activity_log_daily_stats(date, category, status, count, updated_at)
            VALUES (:date, :category, :status, :count, CURRENT_TIMESTAMP)
            ON CONFLICT(date, category, status) DO UPDATE SET
                count = count + excluded.count,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        try:
            for (date_str, category, status), delta in counters.items():
                db.execute(stmt, {
                    "date": date_str,
                    "category": category,
                    "status": status,
                    "count": delta,
                })
        except Exception:
            # 老版本 SQLite（<3.24）不支持 ON CONFLICT；这里吞掉即可，
            # 下次启动的初次回填或 stats 接口的 TTL 缓存会兜底。
            logger.debug("[操作记录] 日聚合 UPSERT 失败（非致命）", exc_info=True)


# ========== 单例 ==========
_writer_singleton: Optional[ActivityLogWriter] = None
_writer_singleton_lock = threading.Lock()


def get_activity_log_writer() -> ActivityLogWriter:
    global _writer_singleton
    if _writer_singleton is None:
        with _writer_singleton_lock:
            if _writer_singleton is None:
                _writer_singleton = ActivityLogWriter()
    return _writer_singleton


def shutdown_activity_log_writer(timeout: float = 5.0) -> None:
    """进程退出前调用，flush 尚未写入的记录。"""
    global _writer_singleton
    if _writer_singleton is None:
        return
    try:
        _writer_singleton.flush_sync(timeout=timeout)
    finally:
        _writer_singleton.shutdown(timeout=timeout)


# ========== Lifecycle 准备执行器 ==========
# log_task_lifecycle_event 在任务 finally 中调用，原本会做 os.walk / ProcessedArchive
# 回查等昂贵操作。Phase 1 把"构造 detail + 入队"整段挪到独立线程池，让任务 finally
# 立刻返回。
_LIFECYCLE_EXECUTOR: Optional[ThreadPoolExecutor] = None
_LIFECYCLE_EXECUTOR_LOCK = threading.Lock()


def _get_lifecycle_executor() -> ThreadPoolExecutor:
    global _LIFECYCLE_EXECUTOR
    if _LIFECYCLE_EXECUTOR is None:
        with _LIFECYCLE_EXECUTOR_LOCK:
            if _LIFECYCLE_EXECUTOR is None:
                _LIFECYCLE_EXECUTOR = ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="activity-log-prep",
                )
    return _LIFECYCLE_EXECUTOR


def submit_lifecycle_prep(func: Callable[..., Any], *args, **kwargs) -> None:
    """把昂贵的 detail 构造丢到后台线程池，不阻塞调用方。"""
    try:
        executor = _get_lifecycle_executor()
        executor.submit(_run_prep_safely, func, *args, **kwargs)
    except RuntimeError:
        # executor 已关闭；回退为同步执行，避免丢失记录
        _run_prep_safely(func, *args, **kwargs)


def _run_prep_safely(func: Callable[..., Any], *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except Exception:
        logger.warning("[操作记录] 后台构造任务周期记录失败", exc_info=True)


def shutdown_lifecycle_executor(timeout: float = 5.0) -> None:
    global _LIFECYCLE_EXECUTOR
    if _LIFECYCLE_EXECUTOR is None:
        return
    try:
        _LIFECYCLE_EXECUTOR.shutdown(wait=True, cancel_futures=False)
    except Exception:
        logger.warning("[操作记录] 关闭 lifecycle 执行器失败", exc_info=True)
    finally:
        _LIFECYCLE_EXECUTOR = None


# ========== 查询 TTL 缓存 ==========
# 列表/统计接口读多写少。用 (查询 key, writer.last_write_ts_bucket) 作为缓存键，
# 一旦有新审计写入，last_write_ts 就会改变，下一次请求自动 miss 命中最新数据；
# 同时给一个 TTL 上限以兜底时钟/边界情况。
class _ActivityLogQueryCache:
    def __init__(self, max_entries: int = 128, ttl_seconds: float = 30.0) -> None:
        self._max_entries = max(8, int(max_entries))
        self._ttl = max(1.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._entries: "dict[tuple, tuple[float, float, Any]]" = {}

    def get(self, key: tuple, current_write_ts: float) -> Any:
        now = time.monotonic()
        with self._lock:
            record = self._entries.get(key)
            if record is None:
                return None
            cached_write_ts, expires_at, payload = record
            if cached_write_ts != current_write_ts or expires_at <= now:
                self._entries.pop(key, None)
                return None
            return payload

    def set(self, key: tuple, current_write_ts: float, payload: Any) -> None:
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            if len(self._entries) >= self._max_entries:
                # 近似 FIFO：直接丢最老的一个
                try:
                    oldest_key = next(iter(self._entries))
                    self._entries.pop(oldest_key, None)
                except StopIteration:
                    pass
            self._entries[key] = (current_write_ts, expires_at, payload)

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()


_QUERY_CACHE: Optional[_ActivityLogQueryCache] = None
_QUERY_CACHE_LOCK = threading.Lock()


def get_activity_log_query_cache() -> _ActivityLogQueryCache:
    global _QUERY_CACHE
    if _QUERY_CACHE is None:
        with _QUERY_CACHE_LOCK:
            if _QUERY_CACHE is None:
                _QUERY_CACHE = _ActivityLogQueryCache()
    return _QUERY_CACHE


# ========== 行级 dict 缓存 ==========
# Phase 4D：activity_logs 是 append-only 表，一旦写入就不再修改。但合并后的查询缓存
# 会被每条新写入 invalidate（writer.last_write_ts 改变）；活动任务期间几乎所有
# list / children 请求都落在 cache miss 路径，每次都要把 5000 行的 detail JSON 再
# orjson.loads 一遍（~460ms 量级）。
#
# 思路：按 id 缓存 row.to_dict() 的结果，跨请求复用。命中率取决于同一窗口内新增数据量；
# 稳态下 5000-row 窗口命中率接近 100%，端到端首屏能从 ~500ms 降到 ~40ms。
#
# 缓存一致性：rows 不可变 → cache 条目永远有效；只在命中 LRU 上限时逐出最老。
from collections import OrderedDict


class _ActivityLogRowDictCache:
    """按 id 缓存 ActivityLog.to_dict() 的 bounded LRU。

    用法：
        cache = get_activity_log_row_dict_cache()
        hits = cache.get_many(candidate_ids)      # {id: dict}
        missing = [i for i in candidate_ids if i not in hits]
        # ... 从 DB 取 missing 行做 to_dict ...
        cache.put_many((rid, dct) for rid, dct in fresh_pairs)

    线程安全：内部加锁，适合多 worker 并发。
    """

    def __init__(self, max_entries: int = 10000) -> None:
        self._max_entries = max(128, int(max_entries))
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def get_many(self, row_ids) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for rid in row_ids:
                if rid is None:
                    continue
                key = str(rid)
                row = self._entries.get(key)
                if row is None:
                    continue
                self._entries.move_to_end(key)
                out[key] = row
        return out

    def put_many(self, pairs) -> None:
        with self._lock:
            for rid, row in pairs:
                if rid is None or not isinstance(row, dict):
                    continue
                key = str(rid)
                if key in self._entries:
                    self._entries.move_to_end(key)
                    self._entries[key] = row
                    continue
                self._entries[key] = row
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"size": len(self._entries), "max_entries": self._max_entries}


_ROW_DICT_CACHE: Optional[_ActivityLogRowDictCache] = None
_ROW_DICT_CACHE_LOCK = threading.Lock()


def get_activity_log_row_dict_cache() -> _ActivityLogRowDictCache:
    global _ROW_DICT_CACHE
    if _ROW_DICT_CACHE is None:
        with _ROW_DICT_CACHE_LOCK:
            if _ROW_DICT_CACHE is None:
                _ROW_DICT_CACHE = _ActivityLogRowDictCache()
    return _ROW_DICT_CACHE
