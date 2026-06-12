"""数据库一键瘦身服务（L1）。

设计目标
========
- 用户在 Settings → 维护与清理 点一次按钮，把当前 ``cache.db`` 的体积尽可能还回磁盘。
- **零数据损失**：不删除任何 ``activity_logs`` 行、不删任何业务表数据。
  仅做：
    1. ``compact_old_activity_logs(older_than_days=N)``：把 N 天前 detail 中的"全量列表"裁掉
       （此前已有的 :mod:`backend.app.core.activity_log_compactor`，循环到 done 为止）。
    2. ``PRAGMA wal_checkpoint(TRUNCATE)``：把 cache.db-wal 合并回主库 + truncate 到 0。
    3. ``VACUUM``：重写主库回收碎片页 / detail 缩小后的空洞。

并发与可观测
============
- 模块级状态机 + ``threading.Lock``：同一时刻只允许一个瘦身任务在跑。
- 后台线程执行（不阻塞 FastAPI event loop），前端轮询
  ``GET /api/database/maintenance/shrink/status`` 拿进度。
- 三阶段都会更新 ``stage`` / ``stage_label`` / 心跳，并在前后各采集一次
  ``db / -wal / -shm`` 文件大小，最终返回 ``freed_bytes``。

VACUUM 注意事项
================
- VACUUM 必须在事务**外**执行；SQLAlchemy 默认 ``engine.connect()`` 会进 transaction，
  这里改用 ``engine.raw_connection() + isolation_level=None`` 走 autocommit。
- VACUUM 期间会拿数据库的排他锁，其它写请求在 ``busy_timeout=30s`` 内排队，
  超时会 500。本服务在 estimate 接口里返回主库当前大小，前端 UI 提示用户在闲时点。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

# 状态机：idle -> running -> done / error。done / error 不会自动回到 idle，
# 必须由前端主动调用 ``reset_status`` 或者再次启动一轮新任务才会清掉。
_STATE_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()  # 仅用于互斥"新启动一次瘦身"
_STATE: Dict[str, Any] = {
    "state": "idle",            # idle / running / done / error
    "stage": None,              # compact / checkpoint / vacuum / finalize
    "stage_label": "",
    "started_at": None,         # ISO 字符串
    "finished_at": None,
    "duration_ms": 0,
    "older_than_days": 30,
    "min_detail_bytes": 8192,
    "before": None,             # _file_sizes 返回值
    "after": None,
    "compact_result": None,
    "checkpoint_result": None,
    "vacuum_ms": 0,
    "freed_bytes": 0,
    "freed_human": "0 B",
    "error": None,
    "heartbeat": None,
}

_STAGE_LABELS = {
    "compact": "正在压缩 30 天前的操作记录详情…",
    "checkpoint": "正在合并 WAL 草稿到主库…",
    "vacuum": "正在重写主库 / 回收空洞页（最耗时）…",
    "post_checkpoint": "正在 truncate VACUUM 副产生的 WAL…",
    "finalize": "正在采集瘦身结果…",
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _human_bytes(n: int) -> str:
    n = int(n or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ("B", "KB", "MB", "GB", "TB")
    idx = 0
    value = float(n)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{sign}{int(value)} {units[idx]}"
    return f"{sign}{value:.2f} {units[idx]}"


def _file_size_safe(path: str) -> int:
    try:
        if not path:
            return 0
        if not os.path.exists(path):
            return 0
        return int(os.path.getsize(path))
    except Exception:
        return 0


def _file_sizes(db_path: str) -> Dict[str, Any]:
    main = _file_size_safe(db_path)
    wal = _file_size_safe(f"{db_path}-wal")
    shm = _file_size_safe(f"{db_path}-shm")
    total = main + wal + shm
    return {
        "main_size_bytes": main,
        "wal_size_bytes": wal,
        "shm_size_bytes": shm,
        "total_size_bytes": total,
        "main_human": _human_bytes(main),
        "wal_human": _human_bytes(wal),
        "shm_human": _human_bytes(shm),
        "total_human": _human_bytes(total),
    }


def _resolve_db_path() -> str:
    """从既有 :mod:`backend.app.models.database` 读 db_path，避免重复实现解析逻辑。"""
    from ..models.database import get_db_path  # 避免循环导入
    return get_db_path()


def _database_runtime_config() -> Dict[str, Any]:
    from ..models.database import _DB_RUNTIME_CONFIG  # 复用引擎启动时的 SQLite 安全参数

    return dict(_DB_RUNTIME_CONFIG)


# ---------------------------------------------------------------------------
# 状态读写
# ---------------------------------------------------------------------------

def _broadcast_shrink_state(snapshot: Dict[str, Any]) -> None:
    try:
        from .realtime_event_service import broadcast_event

        stage = str(snapshot.get("stage") or "")
        state = str(snapshot.get("state") or "idle")
        progress_by_stage = {
            "compact": 20,
            "checkpoint": 45,
            "vacuum": 70,
            "post_checkpoint": 88,
            "finalize": 95,
        }
        if state in {"done", "error"}:
            progress = 100
        elif state == "running":
            progress = progress_by_stage.get(stage, 5)
        else:
            progress = 0
        broadcast_event({
            "type": "maintenance.database_shrink.changed",
            "reason": stage or state,
            "id": "database_shrink",
            "domain": "maintenance",
            "status": state,
            "progress": progress,
            "current_step": str(snapshot.get("stage_label") or ""),
            "updated_at": str(snapshot.get("heartbeat") or _now_iso()),
            "payload": dict(snapshot),
        })
    except Exception:
        logger.debug("[数据库瘦身] 广播实时状态失败", exc_info=True)


def _set_state(**updates: Any) -> None:
    with _STATE_LOCK:
        for key, value in updates.items():
            _STATE[key] = value
        _STATE["heartbeat"] = _now_iso()
        snapshot = dict(_STATE)
    _broadcast_shrink_state(snapshot)


def get_status() -> Dict[str, Any]:
    """快照状态。返回浅拷贝，前端轮询用。"""
    with _STATE_LOCK:
        snapshot = dict(_STATE)
    snapshot["db_path"] = _resolve_db_path()
    return snapshot


def reset_status() -> None:
    """允许前端在 done / error 状态下手动清掉，避免下次进入时仍然展示旧的结果。"""
    with _STATE_LOCK:
        if _STATE["state"] in ("running",):
            return
        _STATE.update({
            "state": "idle",
            "stage": None,
            "stage_label": "",
            "started_at": None,
            "finished_at": None,
            "duration_ms": 0,
            "before": None,
            "after": None,
            "compact_result": None,
            "checkpoint_result": None,
            "vacuum_ms": 0,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "error": None,
            "heartbeat": _now_iso(),
        })


# ---------------------------------------------------------------------------
# 估算
# ---------------------------------------------------------------------------

def estimate(*, older_than_days: int = 30, min_detail_bytes: int = 8192,
             sample_limit: int = 200) -> Dict[str, Any]:
    """汇总数据库现场大小 + activity_logs compact 估算 + 总体可释放预估。

    上层 API 用这个一次性渲染卡片：
    - main / wal / shm / total 的当前字节数
    - compact 估算（采样外推得到的可压缩条数 / 字节）
    - 估算总释放量 = compact 节省字节 + 当前 wal 字节
      （wal 在 ``checkpoint(TRUNCATE)`` 之后会被清零，VACUUM 再把空洞还给磁盘）
    """
    from .activity_log_compactor import estimate_compact_savings  # 局部导入避免循环

    db_path = _resolve_db_path()
    sizes = _file_sizes(db_path)

    try:
        compact = estimate_compact_savings(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            sample_limit=sample_limit,
        )
    except Exception as e:
        logger.warning("[数据库瘦身] estimate_compact_savings 失败：%s", e, exc_info=True)
        compact = {
            "candidate_total": 0,
            "estimated_compactable_total": 0,
            "estimated_saved_bytes": 0,
            "older_than_days": older_than_days,
            "min_detail_bytes": min_detail_bytes,
        }

    estimated_freed = int(compact.get("estimated_saved_bytes", 0) or 0) + int(sizes["wal_size_bytes"] or 0)
    estimated_after = max(0, int(sizes["total_size_bytes"] or 0) - estimated_freed)

    return {
        "db_path": db_path,
        **sizes,
        "compact": compact,
        "estimated_freed_bytes": estimated_freed,
        "estimated_freed_human": _human_bytes(estimated_freed),
        "estimated_after_total_bytes": estimated_after,
        "estimated_after_total_human": _human_bytes(estimated_after),
        "running": get_status()["state"] == "running",
    }


# ---------------------------------------------------------------------------
# 三段式瘦身
# ---------------------------------------------------------------------------

def _do_compact_loop(*, older_than_days: int, min_detail_bytes: int) -> Dict[str, Any]:
    """循环调用 compact_old_activity_logs，直到 done=True 或者命中保险时间预算。

    单轮 5 秒、上限 5000 行；总预算 10 分钟（极端情况：百万级旧记录），
    达到预算后无论 done 与否都返回，让 vacuum 后续仍能跑。
    """
    from .activity_log_compactor import compact_old_activity_logs

    overall_deadline = time.monotonic() + 10 * 60
    aggregate = {
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "saved_bytes": 0,
        "rounds": 0,
        "done": False,
    }

    while True:
        if time.monotonic() > overall_deadline:
            logger.warning("[数据库瘦身] compact 累计超过 10 分钟，提前退出；剩余行下次周期再处理")
            break

        result = compact_old_activity_logs(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
            max_rows=5000,
            chunk_size=200,
            time_budget_seconds=5.0,
        )
        aggregate["rounds"] += 1
        aggregate["scanned"] += int(result.get("scanned", 0) or 0)
        aggregate["updated"] += int(result.get("updated", 0) or 0)
        aggregate["skipped"] += int(result.get("skipped", 0) or 0)
        aggregate["failed"] += int(result.get("failed", 0) or 0)
        aggregate["saved_bytes"] += int(result.get("saved_bytes", 0) or 0)

        _set_state(
            stage="compact",
            stage_label=(
                f"{_STAGE_LABELS['compact']}（已扫描 {aggregate['scanned']} 行 / 更新 "
                f"{aggregate['updated']} 行 / 节省 {_human_bytes(aggregate['saved_bytes'])}）"
            ),
        )

        if result.get("done"):
            aggregate["done"] = True
            break

    return aggregate


def _do_wal_checkpoint_truncate(db_path: str) -> Dict[str, Any]:
    """在独立 sqlite3 直连上跑 ``PRAGMA wal_checkpoint(TRUNCATE)``。

    这一步会把 -wal 合并回主库并把 -wal 文件 truncate 到 0 字节。
    用直连而不是 SQLAlchemy 的连接池，避免和正在跑的会话相互等待事务。
    """
    cfg = _database_runtime_config()
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
        timeout=max(120, int(cfg.get("busy_timeout_ms", 60000) / 1000)),
    )
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"PRAGMA synchronous={cfg.get('synchronous', 'FULL')}")
            cur.execute(f"PRAGMA busy_timeout={cfg.get('busy_timeout_ms', 60000)}")
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            row = cur.fetchone() or (None, None, None)
            return {
                "busy": int(row[0] or 0),
                "log_pages": int(row[1] or 0),
                "checkpointed_pages": int(row[2] or 0),
            }
        finally:
            cur.close()
    finally:
        conn.close()


def _do_vacuum(db_path: str) -> int:
    """执行 VACUUM 并返回毫秒耗时。

    - 关键点：VACUUM 不能在事务里跑。这里用 ``isolation_level=None`` 直接 autocommit。
    - 用单独的 sqlite3 直连：SQLAlchemy 引擎在 ``_sqlite_pragma_on_connect`` 里
      会把 ``journal_mode=WAL`` 等 PRAGMA 也设进来，VACUUM 期间不希望被这些
      session 状态影响；直连最干净。
    - timeout=600s：VACUUM 期间排他锁 + 大库可能跑几分钟，给充足窗口。
    """
    cfg = _database_runtime_config()
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=600)
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"PRAGMA synchronous={cfg.get('synchronous', 'FULL')}")
            cur.execute(f"PRAGMA busy_timeout={cfg.get('busy_timeout_ms', 60000)}")
            t0 = time.monotonic()
            cur.execute("VACUUM")
            elapsed = (time.monotonic() - t0) * 1000.0
            return int(elapsed)
        finally:
            cur.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 启动入口（异步线程）
# ---------------------------------------------------------------------------

def _shrink_worker(*, older_than_days: int, min_detail_bytes: int) -> None:
    db_path = _resolve_db_path()
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    before = _file_sizes(db_path)

    _set_state(
        state="running",
        stage="compact",
        stage_label=_STAGE_LABELS["compact"],
        started_at=started_at,
        finished_at=None,
        duration_ms=0,
        older_than_days=older_than_days,
        min_detail_bytes=min_detail_bytes,
        before=before,
        after=None,
        compact_result=None,
        checkpoint_result=None,
        vacuum_ms=0,
        freed_bytes=0,
        freed_human="0 B",
        error=None,
    )

    try:
        from ..models.database import check_database_health

        precheck = check_database_health(full=False)
        if not precheck.get("ok"):
            raise RuntimeError(f"数据库瘦身前自检失败，已中止: {precheck}")

        # 1) compact ----------------------------------------------------------
        compact_result = _do_compact_loop(
            older_than_days=older_than_days,
            min_detail_bytes=min_detail_bytes,
        )
        _set_state(compact_result=compact_result)

        # 把 activity_logs 列表 / 详情缓存失效，避免 UI 上还显示旧的合并行
        try:
            from .activity_log_writer import (
                get_activity_log_query_cache,
                get_activity_log_row_dict_cache,
            )
            get_activity_log_query_cache().invalidate()
            get_activity_log_row_dict_cache().invalidate()
        except Exception:
            logger.debug("[数据库瘦身] compact 后失效缓存出错（非致命）", exc_info=True)

        # 2) wal_checkpoint(TRUNCATE) ----------------------------------------
        _set_state(stage="checkpoint", stage_label=_STAGE_LABELS["checkpoint"])
        checkpoint_result = _do_wal_checkpoint_truncate(db_path)
        _set_state(checkpoint_result=checkpoint_result)

        # 3) VACUUM -----------------------------------------------------------
        _set_state(stage="vacuum", stage_label=_STAGE_LABELS["vacuum"])
        vacuum_ms = _do_vacuum(db_path)
        _set_state(vacuum_ms=vacuum_ms)

        # 3.5) VACUUM 收尾再 checkpoint(TRUNCATE) 一次 ------------------------
        # WAL 模式下 VACUUM 走 -wal 通道，完成后 -wal 文件可能膨胀到 ~主库大小；
        # 这里再做一次 TRUNCATE 把它合并回主库 + 清空到 0，否则用户看磁盘上
        # cache.db-wal 反而比瘦身前还大。
        _set_state(stage="post_checkpoint", stage_label=_STAGE_LABELS["post_checkpoint"])
        try:
            post_checkpoint = _do_wal_checkpoint_truncate(db_path)
            _set_state(checkpoint_result={
                **(checkpoint_result or {}),
                "post_busy": post_checkpoint["busy"],
                "post_log_pages": post_checkpoint["log_pages"],
                "post_checkpointed_pages": post_checkpoint["checkpointed_pages"],
            })
        except Exception:
            logger.warning("[数据库瘦身] VACUUM 后再次 checkpoint(TRUNCATE) 失败，-wal 可能未瘦身", exc_info=True)

        # 4) finalize ---------------------------------------------------------
        _set_state(stage="finalize", stage_label=_STAGE_LABELS["finalize"])
        postcheck = check_database_health(full=False)
        if not postcheck.get("ok"):
            raise RuntimeError(f"数据库瘦身后自检失败: {postcheck}")
        after = _file_sizes(db_path)
        freed = max(0, int(before["total_size_bytes"] or 0) - int(after["total_size_bytes"] or 0))
        duration_ms = int((time.monotonic() - started_monotonic) * 1000.0)
        _set_state(
            state="done",
            stage=None,
            stage_label="",
            finished_at=_now_iso(),
            duration_ms=duration_ms,
            after=after,
            freed_bytes=freed,
            freed_human=_human_bytes(freed),
        )
        logger.info(
            "[数据库瘦身] 完成：扫描 %s 行 / 更新 %s 行 / VACUUM %sms / 释放 %s（%s -> %s）",
            compact_result.get("scanned", 0),
            compact_result.get("updated", 0),
            vacuum_ms,
            _human_bytes(freed),
            before["total_human"],
            after["total_human"],
        )
    except Exception as e:
        logger.error("[数据库瘦身] 失败：%s", e, exc_info=True)
        # 即使中途失败，也尝试采集当前的 after 大小，方便用户判断是否仍然有部分进展
        try:
            after = _file_sizes(db_path)
        except Exception:
            after = None
        freed = 0
        if after and before:
            freed = max(0, int(before["total_size_bytes"] or 0) - int(after["total_size_bytes"] or 0))
        duration_ms = int((time.monotonic() - started_monotonic) * 1000.0)
        _set_state(
            state="error",
            stage=None,
            stage_label="",
            finished_at=_now_iso(),
            duration_ms=duration_ms,
            after=after,
            freed_bytes=freed,
            freed_human=_human_bytes(freed),
            error=str(e),
        )
    finally:
        # 释放运行锁；状态本身保留，前端能继续看到 done / error 结果
        try:
            _RUN_LOCK.release()
        except Exception:
            logger.debug("[数据库瘦身] _RUN_LOCK release 时已经被释放", exc_info=True)


def start_shrink(*, older_than_days: int = 30, min_detail_bytes: int = 8192) -> Dict[str, Any]:
    """启动一次瘦身。如果已有任务在跑则返回 ``already_running=True``。

    返回的是当下的状态快照，前端拿到后立刻可以渲染初始进度，再继续轮询 status。
    """
    older_than_days = max(1, int(older_than_days or 30))
    min_detail_bytes = max(0, int(min_detail_bytes or 0))

    if not _RUN_LOCK.acquire(blocking=False):
        logger.info("[数据库瘦身] 启动请求被忽略：已有任务运行中")
        return {"started": False, "already_running": True, "status": get_status()}

    # acquire 成功后把状态切回 running 之前先重置一遍，避免上一轮 done 的字段污染
    with _STATE_LOCK:
        _STATE.update({
            "state": "running",
            "stage": "compact",
            "stage_label": _STAGE_LABELS["compact"],
            "started_at": _now_iso(),
            "finished_at": None,
            "duration_ms": 0,
            "older_than_days": older_than_days,
            "min_detail_bytes": min_detail_bytes,
            "before": None,
            "after": None,
            "compact_result": None,
            "checkpoint_result": None,
            "vacuum_ms": 0,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "error": None,
            "heartbeat": _now_iso(),
        })

    thread = threading.Thread(
        target=_shrink_worker,
        kwargs={"older_than_days": older_than_days, "min_detail_bytes": min_detail_bytes},
        name="database-shrink",
        daemon=True,
    )
    thread.start()
    logger.info(
        "[数据库瘦身] 已启动: older_than_days=%s min_detail_bytes=%s",
        older_than_days,
        min_detail_bytes,
    )
    return {"started": True, "already_running": False, "status": get_status()}
