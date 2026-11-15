"""独立测试 schema 的操作投影基准；不连接生产、不修改现有测试表。"""
from __future__ import annotations

import argparse
import json
import math
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder
from tests.postgres_test_utils import create_postgres_test_engine
from app.models.database import (
    ActivityLog, ActivityLogDailyStats, ActivityLogRollup, ActivityLogOperation,
    ActivityLogOperationEvent, ActivityLogOperationMember, ActivityLogOperationFile,
    ActivityLogMetricFact, ActivityLogProjectionState, ActivityLogProjectionRepair,
    ActivityLogDetailArchive, ActivityLogOperationDaily,
)
from app.core.activity_operation_projection import maintain_operations
from app.core.activity_operation_queries import list_operations, operation_stats, operation_detail
from app.core.activity_log_writer import ActivityLogWriter
from app.core.activity_log_rollup_service import get_activity_log_rollup_service


def p95(values):
    return round(sorted(values)[max(0, math.ceil(len(values) * .95) - 1)], 3)


def fixtures(count, prefix):
    rows = []
    for number in range(count):
        session = f"{prefix}-{number}"
        for stage in range(6):
            rows.append(dict(
                id=str(uuid4()), category="asmr_sync", session_key=session, task_id=session,
                action="session_completed" if stage == 5 else "session_started",
                status="success" if stage == 5 else "processing", summary=f"测试会话 {number}",
                searchable_text=f"测试会话 {number} 宽搜索",
                created_at=datetime(2026, 11, 11, 12) + timedelta(seconds=stage),
                detail={"session_id": session, **({
                    "success_count": 251, "downloaded_bytes": 251000, "download_duration_ms": 1000,
                    "download_files": [{"relative_path": f"{index}.flac", "size_bytes": 1000}
                                       for index in range(251)] if number == 0 else [],
                } if stage == 5 else {})}))
    return rows


def timed_read(engine, count, repetitions):
    report = {"operations": count, "events": count * 6}
    functions = {
        "list": lambda db: list_operations(db, 1, limit=50),
        "filtered_list": lambda db: list_operations(db, 1, limit=50, q="宽搜索", status="success"),
        "stats": lambda db: operation_stats(db, 1, start_date="2026-11-11", end_date="2026-11-11"),
    }
    with Session(engine) as db:
        target = db.query(ActivityLogOperation).filter(
            ActivityLogOperation.generation == 1,
            ActivityLogOperation.identity_value.like("%-0")).one().operation_id
    functions["detail"] = lambda db: operation_detail(db, 1, target)
    for name, run in functions.items():
        durations, statements, payloads = [], [], []
        for _ in range(repetitions):
            seen = []
            def capture(conn, cursor, statement, parameters, context, executemany):
                seen.append(statement)
            event.listen(engine, "before_cursor_execute", capture)
            try:
                with Session(engine) as db:
                    started = perf_counter()
                    result = run(db)
                    durations.append((perf_counter() - started) * 1000)
                    payloads.append(len(json.dumps(jsonable_encoder(result), ensure_ascii=False).encode()))
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            statements.append(len(seen))
        report[name] = {"first_ms": round(durations[0], 3), "warm_p95_ms": p95(durations[1:]),
                        "sql_count": max(statements), "payload_bytes": max(payloads)}
        # 内存采样单独执行，避免 tracemalloc 干扰延迟统计。
        tracemalloc.start()
        try:
            with Session(engine) as db:
                result = run(db)
                json.dumps(jsonable_encoder(result), ensure_ascii=False)
            report[name]["python_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    report["local_latency_pass"] = (
        report["list"]["warm_p95_ms"] + report["stats"]["warm_p95_ms"] <= 300
        and report["list"]["first_ms"] + report["stats"]["first_ms"] <= 1000
        and report["detail"]["warm_p95_ms"] <= 1000)
    with engine.begin() as connection:
        report["page_plan"] = connection.execute(text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT * FROM activity_log_operations WHERE generation=1
            ORDER BY latest_activity_at DESC, operation_id DESC LIMIT 50
        """)).scalar()
    return report


def write_sample(engine, rows, mode):
    started = perf_counter()
    for offset in range(0, len(rows), 120):
        chunk = rows[offset:offset + 120]
        with Session(engine) as db, db.begin():
            ActivityLogWriter._insert_batch(db, chunk)
            ActivityLogWriter._upsert_daily_stats(db, chunk, strict=True)
            if mode == "legacy":
                get_activity_log_rollup_service().upsert_from_payloads(db, chunk)
            else:
                maintain_operations(db, chunk, generation=1)
    return len(rows) / (perf_counter() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=int, default=100)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/activity-performance.json")
    options = parser.parse_args()
    if options.operations < 1 or options.repetitions < 3:
        parser.error("operations 必须为正数，repetitions 至少为 3")
    admin = create_postgres_test_engine()
    schema = "activity_bench_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(admin.url, connect_args={"options": f"-csearch_path={schema},public"})
    models = (ActivityLog, ActivityLogDailyStats, ActivityLogRollup, ActivityLogOperation,
              ActivityLogOperationEvent, ActivityLogOperationMember, ActivityLogOperationFile,
              ActivityLogMetricFact, ActivityLogProjectionState, ActivityLogProjectionRepair,
              ActivityLogDetailArchive, ActivityLogOperationDaily)
    report = {"kind": "synthetic_local_postgresql", "database_cache": "未清空 PostgreSQL/操作系统缓存",
              "scales": [], "write": {}}
    try:
        ActivityLog.metadata.create_all(engine, tables=[model.__table__ for model in models])
        for scale in (1, 10):
            count = options.operations * scale
            rows = fixtures(count, f"scale-{scale}")
            with Session(engine) as db, db.begin():
                for offset in range(0, len(rows), 120):
                    chunk = rows[offset:offset + 120]
                    ActivityLogWriter._insert_batch(db, chunk)
                    maintain_operations(db, chunk, generation=1)
            with engine.begin() as connection:
                connection.execute(text("ANALYZE"))
            report["scales"].append(timed_read(engine, count, options.repetitions))
            with engine.begin() as connection:
                for model in reversed(models):
                    connection.execute(model.__table__.delete())
        for mode in ("legacy", "projection"):
            report["write"][mode + "_events_per_second"] = round(
                write_sample(engine, fixtures(options.operations, mode), mode), 2)
        baseline = report["write"]["legacy_events_per_second"]
        measured = report["write"]["projection_events_per_second"]
        report["write"]["regression_percent"] = round((1 - measured / baseline) * 100, 2)
        report["write"]["within_10_percent"] = measured >= baseline * .9
        report["concurrent_write"] = {"workers": 4}
        for mode in ("legacy", "projection"):
            samples = [fixtures(options.operations, f"concurrent-{mode}-{worker}") for worker in range(4)]
            started = perf_counter()
            with ThreadPoolExecutor(max_workers=4) as workers:
                # 每个线程使用独立事务、操作身份，记录同负载下的总吞吐。
                list(workers.map(lambda rows: write_sample(engine, rows, mode), samples))
            report["concurrent_write"][mode + "_events_per_second"] = round(
                sum(map(len, samples)) / (perf_counter() - started), 2)
        baseline = report["concurrent_write"]["legacy_events_per_second"]
        measured = report["concurrent_write"]["projection_events_per_second"]
        report["concurrent_write"]["regression_percent"] = round((1 - measured / baseline) * 100, 2)
        report["concurrent_write"]["within_10_percent"] = measured >= baseline * .9
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**report, "scales": [
            {key: value for key, value in scale.items() if key != "page_plan"}
            for scale in report["scales"]]}, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
