import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api import routes
from app.core.library_circle_grouping import group_local_folders
from app.core.library_manager import LibraryDefinition, LibraryManager


@pytest.fixture
def context(tmp_path):
    library = LibraryDefinition(id="circle-test", name="社团分类测试", type="local", path=str(tmp_path))
    manager = object.__new__(LibraryManager)
    manager._stats_cache = {library.id: {"status": "completed", "scan_mode": "manual_persisted", "folder_count": 0}}
    manager._persist_stats = Mock()
    manager._invalidate_local_browse_caches = Mock()
    manager._append_stats_log = Mock()
    service = Mock()
    service.prepare.return_value = SimpleNamespace(operation_id="batch")
    service.finalize.side_effect = lambda _, **kw: {**kw["actual_result"], "index_fences": [{"library_id": library.id, "seq": 1}]}
    return manager, library, service


def run_group(context, paths, **kwargs):
    manager, library, service = context
    return group_local_folders(manager, library, [str(p) for p in paths], routes._parse_circle_name_from_folder, service, **kwargs)


def test_unknown_circle_has_no_side_effect(context, tmp_path):
    source = tmp_path / "RJ123456 无社团"
    source.mkdir()
    (source / "音声.wav").write_bytes(b"original")
    result = run_group(context, [source])
    assert result["failed_count"] == 1
    assert "未操作" in result["results"][0]["error"]
    assert (source / "音声.wav").read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [source]
    context[2].prepare.assert_not_called()
    context[0]._persist_stats.assert_not_called()


@pytest.mark.parametrize("count", [10, 100, 500])
def test_batch_constant_transaction_count(context, tmp_path, count):
    paths = []
    for n in range(count):
        source = tmp_path / f"[社团{n % 5}][RJ{123456 + n}]作品"
        source.mkdir()
        (source / "音声.wav").write_bytes(b"audio")
        paths.append(source)
    context[0]._stats_cache[context[1].id]["folder_count"] = count
    started = time.perf_counter()
    result = run_group(context, paths)
    elapsed = time.perf_counter() - started
    print(f"纯文件系统+模拟索引提交 count={count} elapsed_ms={elapsed * 1000:.2f}")
    assert result["success_count"] == count
    assert result["failed_count"] == 0
    for item in result["results"]:
        from pathlib import Path
        assert (Path(item["final_path"]) / "音声.wav").read_bytes() == b"audio"
    service = context[2]
    service.prepare.assert_called_once()
    service.mark_filesystem_started.assert_called_once_with("batch")
    service.finalize.assert_called_once()
    context[0]._persist_stats.assert_called_once()
    context[0]._invalidate_local_browse_caches.assert_called_once()
    assert context[0]._stats_cache[context[1].id]["folder_count"] == 5


def test_merge_preserves_both_conflicting_files(context, tmp_path):
    source = tmp_path / "[社团][RJ123456]作品"
    destination = tmp_path / "社团" / source.name
    source.mkdir()
    destination.mkdir(parents=True)
    (source / "音声.wav").write_bytes(b"new")
    (destination / "音声.wav").write_bytes(b"old")
    result = run_group(context, [source])
    assert result["success_count"] == 1
    assert not source.exists()
    assert sorted(p.read_bytes() for p in destination.iterdir()) == [b"new", b"old"]
    effects = context[2].finalize.call_args.kwargs["actual_effects_by_library"][context[1].id]
    assert {e["kind"] for e in effects} == {"reconcile"}
    assert len(effects) == 2


def test_directory_conflicting_with_file_uses_suffix_and_recovery_covers_it(context, tmp_path):
    source = tmp_path / "[社团][RJ123456]作品"
    source.mkdir()
    (source / "音声.wav").write_bytes(b"audio")
    target = tmp_path / "社团"
    target.mkdir()
    blocker = target / source.name
    blocker.write_bytes(b"keep")
    result = run_group(context, [source])
    assert result["success_count"] == 1
    from pathlib import Path
    final = Path(result["results"][0]["final_path"])
    assert final != blocker and (final / "音声.wav").read_bytes() == b"audio"
    assert blocker.read_bytes() == b"keep"
    planned = context[2].prepare.call_args.kwargs["effects_by_library"][context[1].id]
    assert {"kind": "reconcile", "relative_path": "社团", "scope": "subtree"} in planned


def test_invalid_item_does_not_prevent_valid_item(context, tmp_path):
    invalid = tmp_path / "RJ123456"
    valid = tmp_path / "[社团][RJ123457]作品"
    invalid.mkdir()
    valid.mkdir()
    result = run_group(context, [invalid, valid])
    assert result["success_count"] == result["failed_count"] == 1
    assert invalid.is_dir()
    assert not valid.exists()


def test_overlapping_selection_is_untouched(context, tmp_path):
    parent = tmp_path / "[社团][RJ123456]作品"
    child = parent / "RJ123457"
    child.mkdir(parents=True)
    result = run_group(context, [parent, child])
    assert result["failed_count"] == 2
    assert child.is_dir()
    context[2].prepare.assert_not_called()


def test_preview_and_already_grouped_do_not_prepare(context, tmp_path):
    source = tmp_path / "社团" / "[社团][RJ123456]作品"
    source.mkdir(parents=True)
    assert run_group(context, [source])["skipped_count"] == 1
    other = tmp_path / "[社团][RJ123457]作品"
    other.mkdir()
    assert run_group(context, [other], preview=True)["results"][0]["preview"]
    assert other.is_dir()
    context[2].prepare.assert_not_called()


def test_partial_merge_failure_reconciles_both_paths(context, tmp_path, monkeypatch):
    source = tmp_path / "[社团][RJ123456]作品"
    target = tmp_path / "社团" / source.name
    source.mkdir()
    target.mkdir(parents=True)
    monkeypatch.setattr(context[0], "_merge_local_directory_into", lambda *a: {
        "removed_source": False, "failed": [{"error": "文件被占用"}], "skipped": []})
    result = run_group(context, [source])
    assert result["failed_count"] == 1
    assert source.is_dir()
    effects = context[2].finalize.call_args.kwargs["actual_effects_by_library"][context[1].id]
    assert len(effects) == 2
    assert all(e["kind"] == "reconcile" for e in effects)


def test_finalize_failure_keeps_recovery_intent(context, tmp_path):
    source = tmp_path / "[社团][RJ123456]作品"
    source.mkdir()
    context[2].finalize.side_effect = RuntimeError("提交失败")
    with pytest.raises(RuntimeError, match="提交失败"):
        run_group(context, [source])
    assert not source.exists()
    assert (tmp_path / "社团" / source.name).is_dir()
    context[2].mark_reconcile_required.assert_called_once()


def test_route_moves_all_sync_work_off_event_loop(context, tmp_path, monkeypatch):
    main_thread = threading.get_ident()
    calls = []

    def resolve(_):
        calls.append(threading.get_ident())
        return context[:2]

    def parse(_):
        calls.append(threading.get_ident())
        return "社团"

    monkeypatch.setattr(routes, "_resolve_local_auto_circle_group_context", resolve)
    monkeypatch.setattr(routes, "_parse_circle_name_from_folder", parse)
    monkeypatch.setattr(routes, "get_library_index_mutation_service", lambda: context[2])
    source = tmp_path / "[社团][RJ123456]作品"
    source.mkdir()
    result = asyncio.run(routes.batch_auto_circle_group_by_rj(routes.LibraryBatchAutoCircleGroupRequest(
        library_id=context[1].id, row_paths=[str(source)])))
    assert result["success_count"] == 1
    assert calls and all(t != main_thread for t in calls)
