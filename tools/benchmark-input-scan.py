"""真实目录和 PostgreSQL 的扫描协调基准；业务预检及执行器使用明确的模拟边界。"""

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def sample(database_url, workers, interval):
    from sqlalchemy import create_engine, text, update
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from app.config.settings import AppConfig
    from app.core import input_scan_service as module
    from app.core.input_scan_repository import InputScanRepository
    from app.core.task_engine import Task
    from app.models.database import Base, Task as TaskRecord

    url = make_url(database_url)
    if not (url.database or "").endswith("_benchmark"):
        raise ValueError("基准仅允许使用名称以 _benchmark 结尾的隔离数据库")
    schema = "benchmark_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    service = None
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with tempfile.TemporaryDirectory(prefix="scan-benchmark-") as directory:
            for index in range(100):
                suffixes = [".zip"] if index < 70 else [".7z.001", ".7z.002", ".7z.003"]
                for suffix in suffixes:
                    signature = b"PK\x03\x04" if suffix == ".zip" else b"7z\xbc\xaf\x27\x1c"
                    Path(directory, f"RJ{index:08d}{suffix}").write_bytes(signature + b"fixture")
            config = AppConfig()
            config.storage.input_path = directory
            config.processing.max_workers = workers
            config.processing.file_stable_checks = 3
            config.processing.file_stable_interval = interval
            config.input_scan.progress_interval_seconds = 0.5
            repository = InputScanRepository(factory)
            service = module.InputScanService(repository)
            first_submit = None
            started = time.perf_counter()
            commit = repository.commit_candidate

            def timed_commit(*args, **kwargs):
                nonlocal first_submit
                result = commit(*args, **kwargs)
                if result and first_submit is None:
                    first_submit = time.perf_counter() - started
                return result

            repository.commit_candidate = timed_commit

            def complete(task_id):
                with factory.begin() as db:
                    db.execute(update(TaskRecord).where(TaskRecord.id == task_id).values(status="completed"))

            async def acknowledge(task_id):
                # 仅模拟消费以释放交接水位，不记录 task_start 或 extract 时间。
                await asyncio.to_thread(complete, task_id)

            executor = SimpleNamespace(
                get_all_tasks=lambda **kwargs: [],
                try_acquire_input_preflight=lambda candidate_id: True,
                release_input_preflight=lambda candidate_id: None,
                _preflight_auto_process=AsyncMock(return_value=("RJ01234567", True)),
                enqueue_once=acknowledge,
                refresh_input_metadata_window=AsyncMock(),
            )
            with (
                patch.object(module, "get_config", return_value=config),
                patch.object(module, "get_task_engine", return_value=executor),
                patch.object(Task, "_global_event_hook", None),
                patch("app.core.realtime_event_service.broadcast_event"),
            ):
                accepted = await service.start()
                accept_seconds = time.perf_counter() - started
                await asyncio.wait_for(asyncio.shield(service._task), 120)
                duration = time.perf_counter() - started
                result = await service.get(accepted["scan_id"])
                await service.stop()
                assert result["counts"] == {"submitted": 100}, result
                assert result["coverage"]["enumerated_files"] == 160, result
                assert "first_extract_at" not in result["coverage"]
                return {
                    "accept_seconds": round(accept_seconds, 4),
                    "first_handoff_seconds": round(first_submit, 4),
                    "scan_closed_seconds": round(duration, 4),
                    "logical_groups": result["discovered_groups"],
                    "physical_files": result["coverage"]["enumerated_files"],
                    "first_extract_seconds": None,
                }
    finally:
        if service:
            await service.stop()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--stable-interval", type=float, default=0.1)
    args = parser.parse_args()
    if args.samples < 1 or args.workers < 1 or args.stable_interval <= 0:
        parser.error("样本数、并发和稳定间隔必须大于零")
    database_url = os.environ.get("KIKOERUMANAGER_BENCHMARK_DATABASE_URL")
    if not database_url:
        parser.error("请指定 KIKOERUMANAGER_BENCHMARK_DATABASE_URL 隔离数据库")
    logging.disable(logging.CRITICAL)
    results = [
        asyncio.run(sample(database_url, args.workers, args.stable_interval))
        for _ in range(args.samples)
    ]
    print(json.dumps({
        "scope": "协调层：真实发现、归组、稳定采样和 PostgreSQL 交接；模拟业务预检和消费",
        "cache": "同一进程顺序采样，未清理操作系统缓存",
        "workers": args.workers, "stable_checks": 3, "stable_interval": args.stable_interval,
        "samples": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
