"""手动、只读的存储同窗观测；不重置统计、不触发 checkpoint 或 Redis 持久化。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import platform
import threading
import time

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


_SAMPLE_LOCK = threading.Lock()
_PG_SETTINGS = (
    "track_io_timing", "track_wal_io_timing", "log_checkpoints", "logging_collector",
    "log_rotation_age", "log_rotation_size", "log_truncate_on_rotation",
)
_REDIS_PERSISTENCE_FIELDS = (
    "loading", "rdb_bgsave_in_progress", "rdb_last_bgsave_status",
    "rdb_last_bgsave_time_sec", "rdb_current_bgsave_time_sec", "rdb_changes_since_last_save",
    "aof_enabled", "aof_rewrite_in_progress", "aof_rewrite_scheduled",
    "aof_last_rewrite_time_sec", "aof_current_rewrite_time_sec", "aof_last_bgrewrite_status",
    "aof_last_write_status", "aof_current_size", "aof_base_size", "aof_pending_bio_fsync",
    "aof_delayed_fsync", "current_cow_peak", "current_cow_size", "rdb_last_cow_size",
    "aof_last_cow_size",
)


class StorageObservationBusyError(RuntimeError):
    """当前进程已有一次手动采样。"""


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _unavailable(exc: Exception) -> dict:
    # 连接异常可能含连接地址和 SQL；只输出异常类型。
    return {"status": "unavailable", "error_type": type(exc).__name__}


def _postgres_snapshot() -> dict:
    from ..models.database import engine

    # 单次诊断独占一个短连接，不等待业务连接池，也不占用业务池令牌。
    diagnostic_engine = create_engine(
        engine.url, poolclass=NullPool,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=1500 -c transaction_timeout=4000 -c default_transaction_read_only=on"},
    )
    with diagnostic_engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '1500ms'"))
        waits = conn.execute(text(
            "SELECT state, wait_event_type, wait_event, count(*) AS connections "
            "FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
            "GROUP BY state, wait_event_type, wait_event"
        )).mappings().all()
        result = {"status": "ok", "waits": [dict(row) for row in waits]}
        result["visibility"] = dict(conn.execute(text(
            "SELECT current_setting('server_version_num') AS server_version_num, "
            "pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') OR "
            "current_setting('is_superuser')::boolean AS can_read_all_stats"
        )).mappings().one())
        # PostgreSQL 18 已把 WAL write/sync 计数移到 pg_stat_io；不虚构旧版本列。
        for name, view in (("wal", "pg_stat_wal"), ("checkpointer", "pg_stat_checkpointer"),
                           ("bgwriter", "pg_stat_bgwriter")):
            row = conn.execute(text(f"SELECT * FROM {view}")).mappings().one()
            result[name] = {key: _json_value(value) for key, value in row.items()}
        io_rows = conn.execute(text(
            "SELECT backend_type, object, context, reads, read_time, writes, write_time, "
            "fsyncs, fsync_time, stats_reset FROM pg_stat_io"
        )).mappings().all()
        result["io"] = [{key: _json_value(value) for key, value in row.items()} for row in io_rows]
        settings = conn.execute(text(
            "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(:names)"
        ), {"names": list(_PG_SETTINGS)}).mappings().all()
        result["settings"] = {row["name"]: {"value": row["setting"], "unit": row["unit"]} for row in settings}
        return result


def _redis_snapshot() -> dict:
    from redis import ConnectionPool, Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    from .redis_service import get_redis_service

    source = get_redis_service().client()
    if source is None:
        return {"status": "unavailable", "reason": "redis_disabled"}
    kwargs = dict(source.connection_pool.connection_kwargs)
    kwargs.update(socket_timeout=2.0, retry=Retry(NoBackoff(), 0))
    if "socket_connect_timeout" in kwargs:
        kwargs["socket_connect_timeout"] = 2.0
    pool = ConnectionPool(connection_class=source.connection_pool.connection_class, **kwargs)
    try:
        return _redis_info(Redis(connection_pool=pool))
    finally:
        pool.disconnect()


def _redis_info(client) -> dict:
    with client.pipeline(transaction=False) as pipe:
        persistence, stats, server = pipe.info("persistence").info("stats").info("server").execute()
    result = {
        "status": "ok",
        "persistence": {key: persistence[key] for key in _REDIS_PERSISTENCE_FIELDS if key in persistence},
        "fork": {key: stats[key] for key in ("latest_fork_usec", "total_forks") if key in stats},
        "uptime_seconds": server.get("uptime_in_seconds"),
        "server_run_id": server.get("run_id"),
    }
    try:
        # 只读白名单；ACL 不允许 CONFIG GET 时仍保留 INFO 实测结果。
        settings = client.config_get("appendonly", "appendfsync", "save")
        result["settings"] = {key: settings.get(key) for key in ("appendonly", "appendfsync", "save")}
    except Exception as exc:
        result["settings"] = _unavailable(exc)
    return result


def _disk_snapshot() -> dict:
    if platform.system() != "Linux":
        return {"status": "unavailable", "reason": "requires_linux_procfs"}
    devices = {}
    for line in Path("/proc/diskstats").read_text(encoding="ascii").splitlines():
        fields = line.split()
        if len(fields) < 14:
            continue
        values = [int(value) for value in fields[3:14]]
        devices[fields[2]] = {
            "reads": values[0], "read_bytes": values[2] * 512, "read_ms": values[3],
            "writes": values[4], "write_bytes": values[6] * 512, "write_ms": values[7],
            "in_flight": values[8], "busy_ms": values[9], "weighted_busy_ms": values[10],
        }
    result = {"status": "ok", "scope": "kernel_visible_devices", "devices": devices}
    try:
        result["pressure_io"] = Path("/proc/pressure/io").read_text(encoding="ascii").strip()
    except OSError:
        result["pressure_io"] = None
    return result


def _capture() -> dict:
    result = {"captured_at": datetime.now(timezone.utc).isoformat()}
    for name, collector in (("postgres", _postgres_snapshot), ("redis", _redis_snapshot),
                            ("disk", _disk_snapshot)):
        started = time.monotonic()
        try:
            result[name] = collector()
        except Exception as exc:
            result[name] = _unavailable(exc)
        result[name]["captured_at"] = datetime.now(timezone.utc).isoformat()
        result[name]["monotonic_seconds"] = time.monotonic()
        result[name]["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result


def _counter_delta(before: dict, after: dict, *, reset: bool = False) -> dict:
    if reset or before.get("stats_reset") != after.get("stats_reset"):
        return {"status": "unavailable", "reason": "statistics_reset"}
    values = {}
    for key, value in after.items():
        previous = before.get(key)
        if isinstance(value, (int, float)) and isinstance(previous, (int, float)):
            if value < previous:
                return {"status": "unavailable", "reason": "counter_decreased"}
            values[key] = value - previous
    return {"status": "ok", "values": values}


def _deltas(before: dict, after: dict) -> dict:
    result = {"postgres": {}, "redis": {}, "disk": {}, "interval_seconds": {}}
    for name in ("postgres", "redis", "disk"):
        first_at = before.get(name, {}).get("monotonic_seconds")
        last_at = after.get(name, {}).get("monotonic_seconds")
        if first_at is not None and last_at is not None:
            result["interval_seconds"][name] = round(last_at - first_at, 3)
    first, last = before["postgres"], after["postgres"]
    if first.get("status") == last.get("status") == "ok":
        for section in ("wal", "checkpointer", "bgwriter"):
            result["postgres"][section] = _counter_delta(first[section], last[section])
        # pg_stat_io 的行顺序不稳定，必须按统计对象对齐，重置则拒绝差分。
        identity_fields = ("backend_type", "object", "context")
        io_counters = ("reads", "read_time", "writes", "write_time", "fsyncs", "fsync_time")
        previous_io = {
            tuple(row[key] for key in identity_fields): row for row in first.get("io", [])
        }
        io_deltas = []
        for row in last.get("io", []):
            identity = tuple(row[key] for key in identity_fields)
            previous = previous_io.get(identity)
            delta = {"status": "unavailable", "reason": "baseline_unavailable"}
            if previous is not None:
                fields = (*io_counters, "stats_reset")
                delta = _counter_delta(
                    {key: previous.get(key) for key in fields},
                    {key: row.get(key) for key in fields},
                )
            io_deltas.append({**dict(zip(identity_fields, identity)), **delta})
        result["postgres"]["io"] = io_deltas
    first, last = before.get("redis", {}), after.get("redis", {})
    if first.get("status") == last.get("status") == "ok":
        if not first.get("server_run_id") or not last.get("server_run_id"):
            result["redis"] = {"status": "unavailable", "reason": "instance_identity_unavailable"}
        else:
            result["redis"] = _counter_delta(
                {"aof_delayed_fsync": first["persistence"].get("aof_delayed_fsync"),
                 "total_forks": first["fork"].get("total_forks")},
                {"aof_delayed_fsync": last["persistence"].get("aof_delayed_fsync"),
                 "total_forks": last["fork"].get("total_forks")},
                reset=first["server_run_id"] != last["server_run_id"],
            )
    first, last = before["disk"], after["disk"]
    if first.get("status") == last.get("status") == "ok":
        for name, counters in last["devices"].items():
            if name in first["devices"]:
                # in_flight 是瞬时队列深度，不是累计计数。
                result["disk"][name] = _counter_delta(
                    {key: value for key, value in first["devices"][name].items() if key != "in_flight"},
                    {key: value for key, value in counters.items() if key != "in_flight"},
                )
    return result


def sample_storage_observation(interval_seconds: float = 1.0) -> dict:
    """最多等待十秒采样间隔；间隔内不持有数据库连接或事务。"""
    if not 0.1 <= interval_seconds <= 10:
        raise ValueError("采样间隔必须在 0.1 到 10 秒之间")
    if not _SAMPLE_LOCK.acquire(blocking=False):
        raise StorageObservationBusyError("已有存储观测采样正在运行")
    try:
        started = time.monotonic()
        before = _capture()
        time.sleep(interval_seconds)
        after = _capture()
        from .app_logging import get_app_logging_status
        from .resource_budget_service import get_resource_budget_service

        return {
            "read_only": True, "requested_interval_seconds": interval_seconds,
            "timeouts": {"postgres_connect_seconds": 2, "postgres_transaction_seconds": 4,
                         "postgres_statement_ms": 1500, "redis_socket_seconds": 2, "redis_retries": 0},
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "before": before, "after": after, "delta": _deltas(before, after),
            "resource_budget": get_resource_budget_service().snapshot(),
            "app_logging": get_app_logging_status(),
            "scope_note": "各来源顺序短采样，附各自时间戳与实际间隔，非原子快照。PG/Redis 为当前配置实例；磁盘仅为当前命名空间可见内核设备，不能跨设备求和推算宿主总量。",
        }
    finally:
        _SAMPLE_LOCK.release()
