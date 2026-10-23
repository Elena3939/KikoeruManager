"""批量删除的事实快照、后端树与数据库分页回归。"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.api import routes
from app.core import activity_log_service
from app.core.activity_delete_history import local_delete_snapshot, remote_delete_snapshot, delete_history_detail, delete_tree_sections
from app.core.activity_log_batch_list import list_batch_lite
from app.models.database import ActivityLog


def test_local_snapshot_preserves_nested_and_empty_directories(tmp_path):
    root = tmp_path / "作品"
    nested = root / "作品"
    nested.mkdir(parents=True)
    (root / "空目录").mkdir()
    (nested / "字幕.vtt").write_bytes(b"subtitle")
    snapshot = local_delete_snapshot(str(root))
    detail = delete_history_detail([{"library_id": "lib", "success": True, "deleted_items": snapshot}])
    assert detail["deleted_file_count"] == 1
    assert detail["deleted_folder_count"] == 3
    assert detail["deleted_bytes"] == 8
    assert detail["unknown_size_count"] == 0
    sections = delete_tree_sections(detail)
    nodes = sections[0]["rows"]
    for part in ["lib", *root.as_posix().split("/")]:
        node = next(node for node in nodes if node["label"] == part)
        nodes = node["children"]
    repeated = next(node for node in nodes if node["label"] == "作品")
    assert repeated["children"][0]["label"] == "字幕.vtt"
    assert repeated["children"][0]["sizeText"] == "8 B"
    assert any(node["label"] == "空目录" and node["children"] == [] for node in nodes)


def test_metrics_do_not_mix_libraries_or_count_failed_files():
    snapshot = [{"path": "/作品/a.vtt", "type": "file", "size": 10}]
    detail = delete_history_detail([
        {"library_id": "a", "success": True, "deleted_items": snapshot},
        {"library_id": "a", "success": True, "deleted_items": snapshot},
        {"library_id": "b", "success": True, "deleted_items": snapshot},
        {"library_id": "a", "success": False, "path": "/bad", "type": "file", "size": 100, "error": "locked"},
        {"library_id": "a", "success": True, "path": "/unknown-type"},
        {"library_id": "a", "success": True, "path": "/unknown-size", "type": "file"},
    ])
    assert detail["deleted_file_count"] == 3
    assert detail["deleted_bytes"] == 20
    assert detail["unknown_size_count"] == 1
    assert detail["unknown_type_count"] == 1
    assert len(detail["deleted_items"]) == 5
    sections = delete_tree_sections(detail)
    assert len(sections) == 2
    assert {node["label"] for node in sections[0]["rows"]} == {"a", "b"}


def test_remote_snapshot_reads_all_pages_without_reading_content():
    class Client:
        async def stat(self, path):
            return {"files": [{"path": path, "isdir": True}]}

        async def list(self, path, offset, limit):
            assert path == "/root" and limit == 1000
            count = min(1000, 1001 - offset)
            return {"total": 1001, "files": [
                {"path": f"/root/{i}.vtt", "isdir": False, "additional": {"size": 7}}
                for i in range(offset, offset + count)]}

    snapshot = asyncio.run(remote_delete_snapshot(Client(), "/root"))
    detail = delete_history_detail([{"library_id": "nas", "success": True, "deleted_items": snapshot}])
    assert detail["deleted_file_count"] == 1001
    assert detail["deleted_folder_count"] == 1
    assert detail["deleted_bytes"] == 7007


def test_local_batch_captures_metadata_before_removing_files(tmp_path, monkeypatch):
    from app.core.library_manager import LibraryManager, LibraryDefinition

    root = tmp_path / "作品"
    root.mkdir()
    (root / "字幕.vtt").write_bytes(b"subtitle")
    library = LibraryDefinition(id="local", name="本地测试", type="local", path=str(tmp_path))
    manager = object.__new__(LibraryManager)
    monkeypatch.setattr(manager, "_local_top_level_delta", lambda *args: None)
    monkeypatch.setattr(manager, "_invalidate_local_browse_caches", lambda *args: None)
    monkeypatch.setattr(manager, "_append_stats_log", lambda *args: None)
    response = manager._local_batch_delete(library, [str(root)], confirmed=True, skip_index_mutation=True)
    assert response["success_count"] == 1
    assert not root.exists()
    detail = delete_history_detail(response["audit_results"])
    assert detail["deleted_file_count"] == detail["deleted_folder_count"] == 1
    assert detail["deleted_bytes"] == 8


def test_compaction_keeps_permanent_delete_snapshot():
    from app.core.activity_log_compactor import _compact_detail

    detail = delete_history_detail([{"path": "/作品/a.vtt", "type": "file", "size": 5, "success": True}])
    detail["results"] = [{"path": "/作品/a.vtt", "success": True}]
    compacted, changed, _ = _compact_detail(detail)
    assert changed and "results" not in compacted
    assert compacted["deleted_items"] == detail["deleted_items"]
    assert delete_tree_sections(compacted)[0]["rows"][0]["children"][0]["label"] == "a.vtt"


def _save_delete(db, log_id, action, *, batch="delete-batch", status="success", path=None, detail=None):
    db.add(ActivityLog(id=log_id, category="pipeline_delete", action=action, status=status,
                       summary="删除", source_path=path, batch_id=batch,
                       created_at=datetime(2026, 10, 20, 12), detail=detail or {}))


def test_legacy_delete_batches_page_and_search_as_one_and_detail_is_not_truncated(db_session):
    _save_delete(db_session, "parent", "batch_api_delete", status="partial_success",
                 detail={"success_count": 599, "failed_count": 1, "results": []})
    for i in range(600):
        _save_delete(db_session, f"child-{i}", "batch_delete_item", path=f"/作品/字幕/{i}.vtt",
                     detail={"item_type": "file", "library_id": "nas"}, status="failed" if i == 599 else "success")
    _save_delete(db_session, "unrelated", "delete", batch="other", path="/other")
    db_session.flush()
    query = db_session.query(ActivityLog)
    assert list_batch_lite(db_session, query, page=1, limit=1)["total"] == 2
    result = list_batch_lite(db_session, query.filter(ActivityLog.id == "child-123"), page=1, limit=50, searching=True)
    assert result["total"] == 1
    assert result["items"][0]["id"] == "parent"
    assert result["items"][0]["status"] == "partial_success"
    assert "删除文件" not in {chip["label"] for chip in result["items"][0]["chips"]}
    assert list_batch_lite(db_session, query, page=1, limit=50, status="partial_success")["total"] == 1
    detail = routes.get_activity_log_detail("parent", db=db_session)["row"]["detail"]
    assert len(detail["results"]) == 600
    assert [section["title"] for section in detail["delete_tree_sections"]] == ["已删除（599 项）", "删除失败（1 项）"]


def test_new_batch_lists_compact_metrics_and_fetches_tree_only_in_detail(db_session, monkeypatch):
    captured = []
    monkeypatch.setattr(activity_log_service, "write_activity_log", lambda **kwargs: captured.append(kwargs))
    activity_log_service.log_batch_api_delete_result(batch_id="delete-batch", total_count=600,
        success_count=600, failed_count=0, results=[
            {"path": f"/作品/{i}.vtt", "library_id": "nas", "success": True,
             "deleted_items": [{"path": f"/作品/{i}.vtt", "type": "file", "size": 7}]}
            for i in range(600)])
    assert len(captured) == 1
    payload = captured[0]
    _save_delete(db_session, "parent", payload["action"], detail=payload["detail"])
    db_session.flush()
    statements = []
    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        result = list_batch_lite(db_session, db_session.query(ActivityLog), page=1, limit=50)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert len(statements) == 3
    assert not any("activity_logs.detail AS" in sql for sql in statements)
    assert result["total"] == 1
    assert result["items"][0]["detail"]["deleted_file_count"] == 600
    assert result["items"][0]["detail"]["deleted_bytes"] == 4200
    assert len(json.dumps(result, default=str, ensure_ascii=False)) < 3000
    detail = routes.get_activity_log_detail("parent", db=db_session)["row"]["detail"]
    assert len(detail["deleted_items"]) == len(detail["results"]) == 600
    assert len(detail["delete_tree_sections"][0]["rows"][0]["children"][0]["children"]) == 600


def test_legacy_json_batch_ids_keep_simultaneous_deletes_separate(db_session):
    for batch in ("first", "second"):
        _save_delete(db_session, f"parent-{batch}", "batch_api_delete", batch=None,
                     detail={"batch_id": batch, "success_count": 1})
        _save_delete(db_session, f"child-{batch}", "batch_delete_item", batch=None,
                     path=f"/{batch}/a.vtt", detail={"batch_id": batch, "item_type": "file"})
    _save_delete(db_session, "orphan", "batch_delete_item", batch="missing-parent", path="/orphan.vtt")
    db_session.flush()
    query = db_session.query(ActivityLog)
    result = list_batch_lite(db_session, query, page=1, limit=50)
    assert result["total"] == 3
    assert {item["id"] for item in result["items"]} == {"parent-first", "parent-second", "orphan"}
    for batch in ("first", "second"):
        detail = routes.get_activity_log_detail(f"parent-{batch}", db=db_session)["row"]["detail"]
        assert [item["path"] for item in detail["results"]] == [f"/{batch}/a.vtt"]


@pytest.mark.parametrize("cross_library", [False, True])
def test_delete_api_logs_one_batch_and_keeps_snapshot_out_of_response(monkeypatch, cross_library):
    captured = []
    targets = [{"library_id": "nas", "path": "/作品/a.vtt"}, {"library_id": "nas", "path": "/作品/b.vtt"}]
    audit = [{**target, "success": True, "deleted_items": [{"path": target["path"], "type": "file", "size": 9}]} for target in targets]

    class Manager:
        def get_library_definition(self, library_id):
            return SimpleNamespace(id=library_id, type="synology_filestation")

        async def batch_delete(self, *args, **kwargs):
            return {"success_count": 2, "failed_paths": [], "audit_results": audit}

        async def batch_delete_targets(self, *args, **kwargs):
            return {"success_count": 2, "failed_paths": [], "success_paths": targets, "audit_results": audit}

    class Request:
        headers = {}

        async def json(self):
            return {"confirmed": True, "targets": targets, "library_id": "nas", "paths": [item["path"] for item in targets]}

    monkeypatch.setattr(routes, "get_library_manager", lambda: Manager())
    monkeypatch.setattr(activity_log_service, "write_activity_log", lambda **kwargs: captured.append(kwargs))
    handler = routes.batch_delete_library_browser_targets if cross_library else routes.batch_delete_library_browser_items
    response = asyncio.run(handler(Request()))
    assert len(captured) == 1
    assert captured[0]["action"] == "batch_api_delete"
    assert captured[0]["detail"]["batch_id"] == response["batch_id"]
    assert captured[0]["detail"]["deleted_bytes"] == 18
    assert captured[0]["detail"]["deleted_file_count"] == 2
    assert "audit_results" not in response
