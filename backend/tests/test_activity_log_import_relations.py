"""解压历史的任务身份、批次统计和耗时口径回归。"""
from datetime import datetime

from app.api import routes
from app.core.activity_log_aggregator import merge_activity_rows_from_dicts
from app.core.activity_log_lite import build_lite_item
from app.core.activity_log_batch_list import list_batch_lite
from app.core.activity_log_rollup_service import ActivityLogRollupService
from app.models.database import ActivityLog


def _row(log_id, task_id, *, action="task_finished", status="success", at="2026-10-19T10:10:00", **detail):
    return dict(id=log_id, task_id=task_id, category="auto_import", action=action,
                status=status, summary="完成，耗时 60 秒", created_at=at,
                source_path=f"/archives/{task_id}.zip", batch_id="batch-1",
                session_key="session-12345678", parent_id=None,
                detail={"batch_id": "batch-1", "session_id": "session-12345678", **detail})


def _batch(**detail):
    return _row("parent", "batch-1", action="batch_start", at="2026-10-19T10:00:00",
                created_count=2, archive_count=2, **detail)


def _save(db, rows):
    for row in rows:
        payload = dict(row)
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        db.add(ActivityLog(**payload))
    db.flush()


def test_parallel_batch_uses_wall_clock_and_ignores_side_events_and_duplicate_results():
    rows = [_batch(),
            _row("failed", "task-1", status="failed", at="2026-10-19T10:05:00", archive_size_bytes=100),
            _row("ok", "task-1", archive_size_bytes=100, extract_output_bytes=200, duration_ms=60000),
            _row("other", "task-2", archive_size_bytes=300, extract_output_bytes=400, duration_ms=120000),
            _row("queue", "task-1", action="archive_queued", archive_size_bytes=100)]
    parent = next(row for row in merge_activity_rows_from_dicts(rows) if row["id"] == "parent")
    detail = parent["detail"]
    assert detail["result_task_count"] == 2
    assert detail["extract_completed_count"] == 2
    assert detail["failed_child_count"] == 0
    assert detail["aggregate_archive_size_bytes"] == 400
    assert detail["aggregate_extract_output_bytes"] == 600
    assert detail["batch_duration_ms"] == 600000
    assert {row["id"] for row in detail["child_rows"]} == {"failed", "ok", "other"}


def test_synthetic_batch_infers_start_from_finish_minus_duration():
    rows = [_row("one", "task-1", duration_ms=120000),
            _row("two", "task-2", at="2026-10-19T10:11:00", duration_ms=60000)]
    parent = merge_activity_rows_from_dicts(rows)[0]
    assert parent["detail"]["batch_duration_ms"] == 180000


def test_batch_with_unfinished_tasks_stays_incomplete():
    parent = merge_activity_rows_from_dicts([_batch(), _row("one", "task-1")])[0]
    assert parent["status"] == "incomplete"
    assert merge_activity_rows_from_dicts([_batch()])[0]["status"] == "incomplete"


def test_single_archive_detail_and_children_do_not_expand_siblings(db_session):
    _save(db_session, [_batch(), _row("one", "task-1"), _row("two", "task-2"),
                       _row("queue", "task-1", action="archive_queued")])
    item = routes.get_activity_log_detail("one", db=db_session)["row"]
    assert item["id"] == "one"
    assert "child_total_count" not in item
    assert "总耗时" in item["summary"]
    assert not item.get("detail", {}).get("child_rows")
    assert routes.get_activity_log_children("one", db=db_session)["items"] == []
    batch = routes.get_activity_log_detail("parent", db=db_session)["row"]
    assert {row["id"] for row in batch["detail"]["child_rows"]} == {"one", "two"}
    assert batch["child_success_count"] == 2


def test_import_lite_ignores_stale_event_rollup_and_matches_detail(db_session):
    _save(db_session, [_batch(), _row("one", "task-1", status="failed"),
                       _row("queue", "task-1", action="archive_queued")])
    item = build_lite_item(_batch())
    routes._enrich_lite_items_with_batch_summary([item], db_session)
    assert item["child_total_count"] == 1
    assert item["child_failed_count"] == 1
    assert item["child_success_count"] == 0
    assert item["status"] == routes.get_activity_log_detail("parent", db=db_session)["row"]["status"]


def test_explicit_different_batch_cannot_be_absorbed_by_manifest():
    parent = _batch(created_tasks=[{"task_id": "task-1"}])
    other = _row("one", "task-1")
    other["batch_id"] = other["detail"]["batch_id"] = "other-batch"
    rows = merge_activity_rows_from_dicts([parent, other])
    assert not next(row for row in rows if row["id"] == "parent").get("detail", {}).get("child_rows")


def test_persisted_rollup_counts_latest_task_results(db_session):
    _save(db_session, [_batch(),
                      _row("old", "task-1", status="failed", at="2026-10-19T10:05:00"),
                      _row("one", "task-1"), _row("two", "task-2"),
                      _row("queue", "task-1", action="archive_queued")])
    rollup = ActivityLogRollupService().rebuild_one(db_session, rollup_type="batch", group_value="batch-1")
    assert rollup.parent_log_id == "parent"
    assert rollup.child_count == 2
    assert rollup.success_count == 2
    assert rollup.failed_count == 0


def test_multi_rj_archive_keeps_identity_summary_and_real_children(db_session):
    parent = _row("package", "package-task", multi_rj_subtask_count=2)
    parent["batch_id"] = parent["detail"]["batch_id"] = "package-task"
    children = [_row("child-one", "child-task-1"), _row("child-two", "child-task-2")]
    for child in children:
        child["category"] = "process_existing"
        child["batch_id"] = child["detail"]["batch_id"] = "package-task"
        child["detail"].update(parent_task_id="package-task", source_action="multi_rj_extract_subtask")
    _save(db_session, [parent, *children, _row("unrelated", "other-task")])
    item = routes.get_activity_log_detail("package", db=db_session)["row"]
    assert item["id"] == "package"
    assert item["summary"] == "完成，总耗时 60 秒"
    assert {row["id"] for row in item["detail"]["child_rows"]} == {"child-one", "child-two"}


def test_lite_pages_batches_instead_of_packages_and_returns_aggregate_chips(db_session):
    other = _row("third", "task-3", at="2026-10-19T11:00:00", archive_size_bytes=1024)
    other["batch_id"] = other["detail"]["batch_id"] = "batch-2"
    _save(db_session, [_batch(), _row("one", "task-1", archive_size_bytes=1024),
                      _row("two", "task-2", archive_size_bytes=2048), other])
    query = db_session.query(ActivityLog)
    first = list_batch_lite(db_session, query, page=1, limit=1)
    second = list_batch_lite(db_session, query, page=2, limit=1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] == "synthetic-import-batch:auto_import:batch-2"
    item = second["items"][0]
    assert item["id"] == "parent"
    assert item["detail"]["aggregate_archive_size_bytes"] == 3072
    assert item["child_total_count"] == 2
    assert {chip["label"]: chip["value"] for chip in item["chips"]}["压缩包总大小"] == "3.0 KB"
    assert not item["source_path"] and not item["rjcode"]
    assert "child_rows" not in item["detail"]


def test_search_hit_on_package_returns_whole_batch_not_partial_statistics(db_session):
    _save(db_session, [_batch(), _row("one", "task-1", archive_size_bytes=100),
                      _row("two", "task-2", archive_size_bytes=300)])
    query = db_session.query(ActivityLog).filter(ActivityLog.id == "one")
    result = list_batch_lite(db_session, query, page=1, limit=50, searching=True)
    assert result["total"] == 1
    assert result["items"][0]["id"] == "parent"
    assert result["items"][0]["detail"]["aggregate_archive_size_bytes"] == 400


def test_status_filter_applies_to_batch_after_latest_retry_results(db_session):
    _save(db_session, [_batch(), _row("old", "task-1", status="failed", at="2026-10-19T10:05:00"),
                      _row("one", "task-1"), _row("two", "task-2", status="failed")])
    query = db_session.query(ActivityLog)
    result = list_batch_lite(db_session, query, page=1, limit=50, status="partial_success")
    assert result["total"] == 1
    assert result["items"][0]["status"] == "partial_success"
    assert result["items"][0]["child_total_count"] == 2
    assert list_batch_lite(db_session, query, page=1, limit=50, status="failed")["total"] == 0


def test_synthetic_batch_details_and_children_work_without_batch_start(db_session):
    rows = [_row("one", "task-1", duration_ms=1000), _row("two", "task-2", duration_ms=2000)]
    # 索引列中的批次标识也是事实源，不能只信旧 JSON。
    for row in rows:
        row["detail"].pop("batch_id")
    _save(db_session, rows)
    result = list_batch_lite(db_session, db_session.query(ActivityLog), page=1, limit=50)
    item = result["items"][0]
    detail = routes.get_activity_log_detail(item["id"], db=db_session)["row"]
    assert detail["detail"]["result_task_count"] == 2
    assert {row["id"] for row in detail["detail"]["child_rows"]} == {"one", "two"}
    assert routes.get_activity_log_children(item["id"], db=db_session)["total"] == 2


def test_lite_route_aggregates_imports_without_changing_other_categories(db_session):
    from app.core.activity_log_writer import get_activity_log_query_cache

    other = _row("download", "download-task")
    other["category"] = "http_download"
    _save(db_session, [_batch(), _row("one", "task-1"), _row("two", "task-2"), other])
    get_activity_log_query_cache().invalidate()
    result = routes.list_activity_logs(lite=True, db=db_session)
    assert result["total"] == 2
    assert {row["id"] for row in result["items"]} == {"parent", "download"}


def test_multi_rj_directories_are_not_another_archive_batch_in_lite_list(db_session):
    parent = _row("package", "package-task", multi_rj_subtask_count=2)
    parent["batch_id"] = parent["detail"]["batch_id"] = "package-task"
    children = [_row("child-one", "child-task-1"), _row("child-two", "child-task-2")]
    for child in children:
        child["category"] = "process_existing"
        child["batch_id"] = child["detail"]["batch_id"] = "package-task"
        child["detail"].update(parent_task_id="package-task", source_action="multi_rj_extract_subtask")
    _save(db_session, [parent, *children])
    result = list_batch_lite(db_session, db_session.query(ActivityLog), page=1, limit=50)
    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == "package"


def test_large_batch_is_complete_and_list_never_selects_full_detail(db_session):
    import json
    from sqlalchemy import event

    parent = _batch()
    parent["detail"].update(created_count=600, archive_count=650, requested_count=650)
    rows = [_row(f"log-{index}", f"task-{index}", archive_size_bytes=100,
                 file_tree_items=[{"path": "长路径" * 100}]) for index in range(600)]
    _save(db_session, [parent, *rows])
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        result = list_batch_lite(db_session, db_session.query(ActivityLog), page=1, limit=50)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    item = result["items"][0]
    assert result["total"] == 1
    assert item["child_total_count"] == 600
    assert item["detail"]["participating_archive_count"] == 600
    assert item["detail"]["aggregate_archive_size_bytes"] == 60000
    assert len(statements) == 3  # 分组总数、当页分组、当页紧凑统计；没有逐包查询。
    assert not any("activity_logs.detail AS" in sql for sql in statements)
    assert len(json.dumps(result, ensure_ascii=False, default=str)) < 3000
    detail = routes.get_activity_log_detail("parent", db=db_session)["row"]["detail"]
    assert detail["result_task_count"] == 600  # 详情不能再截断在旧的 500 行。


def test_multi_rj_package_in_shared_batch_does_not_replace_batch_root(db_session):
    _save(db_session, [
        _row("multi", "multi-task", multi_rj_subtask_count=2, archive_size_bytes=100),
        _row("normal", "normal-task", archive_size_bytes=300),
    ])
    result = list_batch_lite(db_session, db_session.query(ActivityLog), page=1, limit=50)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["id"] == "synthetic-import-batch:auto_import:batch-1"
    assert item["detail"]["participating_archive_count"] == 2
    assert item["detail"]["aggregate_archive_size_bytes"] == 400
