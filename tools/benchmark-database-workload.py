"""本机隔离 PostgreSQL 重数据对照；生成结果，不接触现有业务库或外网。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from tests.postgres_test_utils import ensure_test_database_exists, test_database_url
from app.core import task_center_materialization_service as current
from app.core.circle_completion_service import CircleCompletionService
from app.models.database import CircleWork, LibraryOwnedWork, TaskCenterItem
from app.models import database


def metrics(values):
    return {
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(sorted(values)[math.ceil(len(values) * .95) - 1], 3),
        "samples": len(values),
    }


def measure(fn, rounds=5):
    values = []
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        values.append((time.perf_counter() - started) * 1000)
    return metrics(values)


@contextmanager
def count_database_work(engine):
    result = {"statements": 0, "commits": 0}

    def statement(*args):
        result["statements"] += 1

    def commit(*args):
        result["commits"] += 1

    event.listen(engine, "before_cursor_execute", statement)
    event.listen(engine, "commit", commit)
    try:
        yield result
    finally:
        event.remove(engine, "before_cursor_execute", statement)
        event.remove(engine, "commit", commit)


def baseline_module(ref, sessions):
    source = subprocess.check_output([
        "git", "show", f"{ref}:backend/app/core/task_center_materialization_service.py"
    ], cwd=ROOT).decode("utf-8")
    module = types.ModuleType("app.core.task_center_materialization_baseline")
    module.__package__ = "app.core"
    exec(compile(source, module.__name__, "exec"), module.__dict__)
    module.SessionLocal = sessions
    return module, hashlib.sha256(source.encode()).hexdigest()


def seed(engine, task_count, circle_count, payload_bytes):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO task_center_items
              (item_id,engine_task_id,domain,status,kind,title,searchable_text,payload_json,version,created_at,updated_at)
            SELECT 'engine:seed-'||i, 'seed-'||i,
                   CASE WHEN i%2=0 THEN 'http_download' ELSE 'circle_completion' END,
                   CASE WHEN i%20=0 THEN 'processing' ELSE 'completed' END,
                   'extract', '模拟任务 '||i, '模拟任务 '||i||' RJ'||(10000000+i),
                   jsonb_build_object('id','engine:seed-'||i,'entity_id','seed-'||i,
                     'engine_task_id','seed-'||i,'title','模拟任务 '||i,
                     'domain',CASE WHEN i%2=0 THEN 'http_download' ELSE 'circle_completion' END,
                     'status',CASE WHEN i%20=0 THEN 'processing' ELSE 'completed' END,
                     'kind','extract','subtype','work_download','source_path','/library/'||i,
                     'rjcode','RJ'||(10000000+i),'created_at','2026-01-01T00:00:00',
                     'details',jsonb_build_object('metadata',jsonb_build_object(
                         'diagnostic',left(repeat(md5(i::text),:repeats),:payload_bytes)))),
                   1, timestamp '2026-01-01'+i*interval '1 second',
                   timestamp '2026-01-01'+i*interval '1 second'
              FROM generate_series(1,:task_count) i
        """), dict(task_count=task_count, payload_bytes=payload_bytes,
                   repeats=math.ceil(payload_bytes / 32)))
        conn.execute(text("""
            INSERT INTO circle_works
              (id,circle_id,canonical_rjcode,display_rjcode,title,linked_rjcodes)
            SELECT 'circle-'||i, 'RG'||(i%1000), 'RJ'||(10000000+i),
                   'RJ'||(10000000+i), '模拟作品 '||i,
                   jsonb_build_array('RJ'||(10000000+i), 'RJ'||(20000000+i))
              FROM generate_series(1,:circle_count) i
        """), dict(circle_count=circle_count))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM (ANALYZE) task_center_items"))
        conn.execute(text("VACUUM (ANALYZE) circle_works"))


def owned_dataset(count):
    return {
        f"RJ{10000000 + i}": dict(
            owned_rjcodes={f"RJ{10000000 + i}"}, primary_folder_path=f"/library/{i}",
            primary_library_id="local", folder_count=1, folder_size=i * 1024,
            file_count=20, owned_paths=[f"/library/{i}"], has_local_subtitles=False,
            subtitle_file_count=0, subtitle_dir="",
        ) for i in range(count)
    }


def legacy_replace_owned(db, merged):
    # 对照原 sync_local_owned_index 的数据库写入段，保留逐个 ORM add 和整表删除。
    db.query(LibraryOwnedWork).delete()
    for canonical, info in merged.items():
        db.add(LibraryOwnedWork(
            canonical_rjcode=canonical, owned_rjcodes=sorted(info["owned_rjcodes"]),
            primary_folder_path=info["primary_folder_path"], library_id=info["primary_library_id"],
            folder_count=info["folder_count"], folder_size=info["folder_size"],
            file_count=info["file_count"], owned_paths=info["owned_paths"],
            has_local_subtitles=bool(info["has_local_subtitles"]),
            subtitle_file_count=info["subtitle_file_count"], subtitle_dir=info["subtitle_dir"],
            updated_at=datetime.now(),
        ))


def run(engine, sessions, args):
    before_module, source_hash = baseline_module(args.baseline, sessions)
    before = before_module.TaskCenterMaterializationService()
    current.SessionLocal = sessions
    after = current.TaskCenterMaterializationService()
    print("生成隔离测试数据...", flush=True)
    seed(engine, args.tasks, args.works, args.payload_bytes)
    report = dict(
        baseline=args.baseline, baseline_sha256=source_hash,
        baseline_commit=subprocess.check_output(
            ["git", "rev-parse", args.baseline], cwd=ROOT).decode().strip(),
        dataset=dict(tasks=args.tasks, circle_works=args.works, owned_works=args.owned,
                     task_payload_bytes=args.payload_bytes),
        limitations="本机合成数据，2KB 诊断内容可压缩；服务层与 HTTP 接口测试，不含浏览器绘制、NAS 磁盘和真实网络延迟。HTTP 显式启用物化 summary 读路径。",
    )

    print("对比批量写入、重复写入和 SQL 分页...", flush=True)
    batch = [dict(id=f"engine:write-{i}", entity_id=f"write-{i}", title=f"批量任务 {i}",
                  domain="http_download", status="processing") for i in range(args.batch)]
    report["task_write"] = {}
    for label, service in (("before", before), ("after", after)):
        samples = {scenario: [] for scenario in ("insert", "changed", "unchanged")}
        counts_by_scenario = {scenario: {"statements": 0, "commits": 0} for scenario in samples}
        for turn in range(3):
            initial = [{**item, "id": f"{item['id']}-{label}-{turn}"} for item in batch]
            changed = [{**item, "status": "completed"} for item in initial]
            for scenario, rows in (("insert", initial), ("changed", changed), ("unchanged", changed)):
                with count_database_work(engine) as counts:
                    started = time.perf_counter()
                    assert service.upsert_items(rows) == len(rows)
                    samples[scenario].append((time.perf_counter() - started) * 1000)
                assert service.diff_items(rows)["matched"]
                for key, value in counts.items():
                    counts_by_scenario[scenario][key] += value
        report["task_write"][label] = {
            scenario: {**metrics(values), **counts_by_scenario[scenario]}
            for scenario, values in samples.items()
        }
    # 顺序与过滤结果必须完全一致，重复 ID 保持原 CASE 的最后位置语义。
    ids = [f"engine:seed-{i}" for i in range(min(args.tasks, 10000), 0, -1)]
    report["ordered_page"] = {}
    for label, service in (("before", before), ("after", after)):
        result = service.list_items(ordered_ids=ids, status="completed", limit=50, offset=100)
        if label == "before":
            expected = result
        else:
            assert result == expected
        report["ordered_page"][label] = measure(
            lambda: service.list_items(ordered_ids=ids, status="completed", limit=50, offset=100))

    heavy_ids = [f"engine:seed-{i}" for i in range(args.tasks, 0, -1)]
    try:
        before.list_items(ordered_ids=heavy_ids, limit=50)
        report["large_order_before"] = "success"
    except Exception as exc:
        # 异常可能包含完整绑定参数，只记录异常类型，禁止打印查询参数。
        report["large_order_before"] = type(exc).__name__
    report["large_order_after"] = measure(lambda: after.list_items(ordered_ids=heavy_ids, limit=50))

    code = f"RJ{20000000 + args.works // 2}"
    sql_before = """SELECT id FROM circle_works WHERE canonical_rjcode=:canonical
        OR display_rjcode=:canonical OR CAST(linked_rjcodes AS TEXT) LIKE :pattern"""
    sql_after = """SELECT id FROM circle_works WHERE canonical_rjcode=:canonical
        OR display_rjcode=:canonical OR linked_rjcodes @> CAST(:codes AS jsonb)"""
    params = dict(canonical=code, pattern=f'%"{code}"%', codes=json.dumps([code]))
    report["linked_lookup"] = {}
    print("对比关联查询与拥有态快照...", flush=True)
    for label, sql in (("before", sql_before), ("after", sql_after)):
        with engine.connect() as conn:
            found = conn.execute(text(sql), params).scalars().all()
            assert found == [f"circle-{args.works // 2}"]
            report["linked_lookup"][label] = measure(lambda: conn.execute(text(sql), params).all(), 10)
            report["linked_lookup"][label]["plan"] = conn.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params).scalar()

    snapshot = owned_dataset(args.owned)
    report["owned_snapshot"] = {}
    for label, replace in (("before", legacy_replace_owned),
                           ("after", CircleCompletionService._replace_local_owned_snapshot)):
        with sessions.begin() as db:
            replace(db, snapshot)
        with sessions() as db:
            unchanged_time = db.get(LibraryOwnedWork, "RJ10000001").updated_at
        times = []
        counts_total = {"statements": 0, "commits": 0}
        for turn in range(3):
            changed = dict(snapshot)
            changed["RJ10000000"] = {**snapshot["RJ10000000"], "folder_size": 1000 + turn}
            started = time.perf_counter()
            with count_database_work(engine) as counts:
                with sessions.begin() as db:
                    replace(db, changed)
            for key, value in counts.items():
                counts_total[key] += value
            times.append((time.perf_counter() - started) * 1000)
        with sessions() as db:
            assert db.query(LibraryOwnedWork).count() == args.owned
            assert db.get(LibraryOwnedWork, "RJ10000000").folder_size == 1002
            if label == "after":
                assert db.get(LibraryOwnedWork, "RJ10000001").updated_at == unchanged_time
        report["owned_snapshot"][label] = {**metrics(times), **counts_total}

    print("执行正式服务链和 HTTP 搜索、筛选、分页与并发读写...", flush=True)
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.core import task_center_service
    from app.core.task_center_list_projection import backfill_list_projections

    center = task_center_service.TaskCenterService()
    started = time.perf_counter()
    with engine.begin() as conn:
        backfilled = backfill_list_projections(conn)
    report["projection_backfill"] = dict(rows=backfilled, duration_ms=round(
        (time.perf_counter() - started) * 1000, 3))
    with engine.connect() as conn:
        report["projection_storage"] = dict(conn.execute(text("""
            SELECT count(*) AS rows, sum(pg_column_size(list_projection)) AS bytes,
                   round(avg(pg_column_size(list_projection)), 1) AS average_bytes
            FROM task_center_items
        """)).mappings().one())
        report["projection_storage"]["average_bytes"] = float(
            report["projection_storage"]["average_bytes"])
    report["list_stages"] = {}
    report["list_stages"]["identity_projection"] = measure(after.list_identity_projection, 3)
    identities = after.list_identity_projection()
    report["list_stages"]["dedupe"] = measure(lambda: center._dedupe_items(identities), 3)
    report["list_stages"]["sort"] = measure(lambda: center._sort_items(identities), 3)
    report["list_stages"]["counts"] = measure(lambda: center._build_overview_counts(identities), 3)
    del identities
    interactions = [
        {}, {"status": "processing"}, {"domain": "circle_completion"},
        {"search": "模拟任务 123"}, {"search": "%"}, {"offset": args.tasks // 2},
    ]
    # 不进入 TestClient lifespan，不启动 watcher、下载器或应用后台 worker。
    client = TestClient(routes.app)
    from app.config.settings import AppConfig
    benchmark_config = AppConfig(task_center={"materialized_summary_enabled": True})
    with patch.object(current, "_task_center_materialization_service", after), \
         patch.object(task_center_service, "get_task_center_service", return_value=center), \
         patch.object(task_center_service, "get_config", return_value=benchmark_config):
        # 对照上一轮完整读取链，而非仅测数据库内部 SELECT。
        with patch.object(after, "list_summary_page", return_value=None):
            report["full_service_before"] = measure(lambda: center.list_materialized_items(limit=50), 3)
            expected_http = []
            before_http_times = []
            for interaction in interactions:
                started = time.perf_counter()
                response = client.get("/api/task-center/list", params={
                    "mode": "summary", "limit": 50, **interaction})
                assert response.status_code == 200
                expected_http.append(response.json())
                before_http_times.append(round((time.perf_counter() - started) * 1000, 3))
            report["http_interactions_before_ms"] = before_http_times
        service_result = center.list_materialized_items(limit=50)
        assert len(service_result["items"]) == 50
        with count_database_work(engine) as read_counts:
            report["full_service"] = measure(lambda: center.list_materialized_items(limit=50), 3)
        report["full_service"]["database_work"] = read_counts
        http_times = []
        for interaction, expected_body in zip(interactions, expected_http):
            started = time.perf_counter()
            response = client.get("/api/task-center/list", params={"mode": "summary", "limit": 50, **interaction})
            assert response.status_code == 200, response.status_code
            body = response.json()
            assert {k: v for k, v in body.items() if k != "generated_at"} == {
                k: v for k, v in expected_body.items() if k != "generated_at"}
            assert len(body["items"]) <= 50
            assert body["mode"] == "materialized_summary"
            if interaction.get("status"):
                assert body["total"] == args.tasks // 20
                assert all(item["status"] == interaction["status"] for item in body["items"])
            elif interaction.get("domain"):
                assert body["total"] == (args.tasks + 1) // 2
                assert all(item["domain"] == interaction["domain"] for item in body["items"])
            elif interaction.get("search"):
                expected_total = sum(
                    interaction["search"].lower() in f"模拟任务 {i} RJ{10000000+i}".lower()
                    for i in range(1, args.tasks + 1))
                assert body["total"] == expected_total
            else:
                assert body["total"] == args.tasks + args.batch * 6
            http_times.append(dict(params=interaction, duration_ms=round(
                (time.perf_counter() - started) * 1000, 3), total=body["total"]))
        report["http_interactions"] = http_times
        print("追加大批重试、恢复失败与重复等待任务，核对完整响应...", flush=True)
        retry_items = []
        for index in range(min(args.tasks // 10, 10000)):
            old_id = f"retry-old-{index}"
            shared = dict(
                domain="http_download", kind="extract", subtype="work_download",
                source_path=f"/retry/{index}", created_at="2026-01-01T00:00:00",
            )
            retry_items.append(dict(
                shared, id=f"engine:{old_id}", entity_id=old_id, status="processing"))
            metadata = ({"retry_failed_task_id": old_id} if index % 2 else
                        {"recovered_failure_ids": [old_id]})
            retry_items.append(dict(
                shared, id=f"engine:retry-new-{index}", entity_id=f"retry-new-{index}",
                status="waiting_manual" if index % 2 else "completed",
                completed_at="2026-01-02T00:00:00", details={"metadata": metadata}))
            if index % 10 == 0:
                retry_items.extend([
                    dict(id=f"waiting:{index}-{turn}", entity_id=f"waiting-{index}",
                         domain="asmr_sync", kind="asmr_sync_waiting_retry", status="waiting_retry")
                    for turn in range(2)])
        assert after.upsert_items(retry_items) == len(retry_items)
        with patch.object(after, "list_summary_page", return_value=None):
            expected_retry = center.list_materialized_items(limit=50)
            report["retry_chain_before"] = measure(lambda: center.list_materialized_items(limit=50), 3)
        actual_retry = center.list_materialized_items(limit=50)
        assert {k: v for k, v in expected_retry.items() if k != "generated_at"} == {
            k: v for k, v in actual_retry.items() if k != "generated_at"}
        assert actual_retry["total"] == args.tasks + args.batch * 6 + len(retry_items) // 2
        report["retry_chain_after"] = measure(lambda: center.list_materialized_items(limit=50), 3)
        report["retry_chain_dataset"] = dict(
            extra_snapshots=len(retry_items), visible_total=actual_retry["total"],
            counts_by_status=actual_retry["counts_by_status"])
    client.close()

    def mixed(index):
        if index % 4 == 0:
            return after.upsert_items([{**batch[0], "title": f"并发进度 {index}"}]) == 1
        return len(after.list_summary_page(
            limit=50, status_priority=center.STATUS_PRIORITY,
            domain_priority=center.DOMAIN_PRIORITY)["items"]) == 50

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert all(workers.map(mixed, range(20)))
    report["concurrent"] = dict(workers=4, operations=20, duration_ms=round(
        (time.perf_counter() - started) * 1000, 3), passed=True)
    report["correctness"] = "批量内容、分页顺序、筛选计数、精确关联、拥有态差异和并发读写通过"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument("--tasks", type=int, default=100000)
    parser.add_argument("--works", type=int, default=200000)
    parser.add_argument("--owned", type=int, default=30000)
    parser.add_argument("--batch", type=int, default=1000)
    parser.add_argument("--payload-bytes", type=int, default=2048)
    parser.add_argument("--output", type=Path, default=ROOT / ".codex" / "db-workload-result.json")
    args = parser.parse_args()
    if min(args.tasks, args.works, args.owned, args.batch, args.payload_bytes) < 2:
        parser.error("数据规模必须至少为 2")
    url = make_url(test_database_url()).set(database="kikoerumanager_workload_benchmark_test")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("压测只允许连接本机 PostgreSQL")
    ensure_test_database_exists(url.render_as_string(hide_password=False))
    schema = "bench_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"},
                           pool_size=8, json_serializer=database._orjson_dumps)
    sessions = sessionmaker(bind=engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public"))
        for model in (TaskCenterItem, CircleWork, LibraryOwnedWork):
            model.__table__.create(engine)
        with engine.begin() as conn:
            for spec in (*database._POSTGRES_BUSINESS_INDEX_SPECS, *database._POSTGRES_TRIGRAM_INDEX_SPECS):
                if any(f"ON {name}" in spec["sql"] for name in ("task_center_items", "circle_works")):
                    conn.execute(text(spec["sql"]))
        report = run(engine, sessions, args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "linked_lookup"}, ensure_ascii=False, indent=2))
        print("完整报告:", args.output)
    finally:
        engine.dispose()
        # schema 仅来自本次随机生成的标识，绝不清理现有 public schema。
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
