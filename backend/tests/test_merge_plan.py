"""合并计划、单次构建与恢复收口回归。"""
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import merge_plan as plans
from app.core import staged_file_move as moves
from app.core import conflict_resolution_service as resolution
from app.core.folder_compare_service import FolderCompareService
from app.core.merge_journal import MergeJournal


@pytest.fixture
def roots(tmp_path, monkeypatch):
    new, old = tmp_path / "new", tmp_path / "old"
    new.mkdir()
    old.mkdir()
    config = SimpleNamespace(host_enabled=False, journal_path=str(tmp_path / "journals"))
    monkeypatch.setattr(plans, "move_config", lambda: config)
    monkeypatch.setattr(moves, "move_config", lambda: config)
    return new, old


def plan_for(new, old, decisions=None):
    compare = FolderCompareService()
    items = compare.build_compare_items(str(new), str(old))
    return plans.build_plan(str(new), str(old), items, compare.normalize_decisions(items, decisions or {}),
                            items.source_manifest, items.existing_manifest)


def test_all_old_unchanged_but_new_empty_directory_is_change(roots):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "a").write_bytes(b"old")
    assert plan_for(new, old, {"a": "use_old"}).unchanged
    (new / "empty").mkdir()
    assert not plan_for(new, old, {"a": "use_old"}).unchanged


@pytest.mark.parametrize("decisions,expected", [({}, {"a": b"new", "b": b"old"}),
    ({"a": "delete", "b": "delete"}, {}), ({"a": "use_old"}, {"a": b"old", "b": b"old"})])
def test_single_build_mixed_delete_empty(roots, tmp_path, decisions, expected):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "a").write_bytes(b"old")
    (old / "b").write_bytes(b"old")
    plan = plan_for(new, old, decisions)
    destination = tmp_path / "stage"
    destination.mkdir()
    metrics = plans.populate_plan(plan, str(destination))
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == expected
    assert metrics["completed_files"] == len(expected)
    assert metrics["processed_bytes"] == sum(map(len, expected.values()))
    assert (old / "a").read_bytes() == b"old"


@pytest.mark.parametrize("side", [0, 1])
def test_preview_identity_change_rejected_even_same_size(roots, side):
    new, old = roots
    for root in roots:
        (root / "a").write_bytes(b"old")
    plan = plan_for(new, old)
    root = roots[side]
    before = os.stat(root / "a")
    (root / "replacement").write_bytes(b"bad")
    os.replace(root / "replacement", root / "a")
    os.utime(root / "a", ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match="刷新"):
        plan.validate()


def test_filter_selected_file_removed_or_replaced_rejected(roots, tmp_path):
    new, old = roots
    (new / "a").write_bytes(b"new")
    plan = plan_for(new, old)
    stage = tmp_path / "filtered"
    stage.mkdir()
    import shutil
    shutil.copy2(new / "a", stage / "a")
    before = moves.snapshot(stage)
    (stage / "a").unlink()
    with pytest.raises(ValueError, match="过滤"):
        plan.rebind_new(str(stage), before)
    shutil.copy2(new / "a", stage / "a")
    with pytest.raises(ValueError, match="过滤"):
        plan.rebind_new(str(stage), before)


@pytest.mark.asyncio
async def test_unchanged_zero_copy_replace_index_and_retry(roots, tmp_path, monkeypatch):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "a").write_bytes(b"old")
    compare = FolderCompareService()
    items = compare.build_compare_items(str(new), str(old))
    session = resolution.ConflictMergeSession("session", "conflict", str(tmp_path / "workspace"), str(new),
        str(old), "library", "local", items, 0, cleanup_sources={str(new): moves.snapshot(new)})
    service = resolution.ConflictResolutionService()
    service._merge_sessions[session.id] = session
    service._copy_to_stage_with_budget = AsyncMock(side_effect=AssertionError("不应暂存"))
    service._notify_index_after_conflict_resolution = Mock(side_effect=AssertionError("不应更新索引"))
    monkeypatch.setattr(plans, "populate_plan", Mock(side_effect=AssertionError("不应构建")))
    monkeypatch.setattr(moves, "move_path_replacing_sync", Mock(side_effect=AssertionError("不应替换")))
    conflict = SimpleNamespace(id="conflict")
    journal = MergeJournal(conflict.id)
    result = await service._resolve_local_merge(conflict, session, {"a": "use_old"}, journal)
    assert result["outcome"] == "unchanged" and result["processed_bytes"] == 0
    assert not new.exists() and (old / "a").read_bytes() == b"old"
    repeated = await service.resolve_merge(conflict, "missing", {})
    assert repeated == result


@pytest.mark.asyncio
async def test_cleanup_failure_restarts_without_publish(roots, tmp_path, monkeypatch):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "b").write_bytes(b"old")
    compare = FolderCompareService()
    session = resolution.ConflictMergeSession("s", "c", str(tmp_path / "workspace"), str(new), str(old),
        "lib", "local", compare.build_compare_items(str(new), str(old)), 0, source_is_staged=True,
        cleanup_sources={str(new): moves.snapshot(new)})
    service = resolution.ConflictResolutionService()
    service._notify_index_after_conflict_resolution = Mock()
    @asynccontextmanager
    async def acquire(*args, **kwargs):
        yield
    monkeypatch.setattr(resolution, "get_resource_budget_service", lambda: SimpleNamespace(acquire=acquire))
    real_clean = moves._clean_source
    def fail(source, *args):
        if source == str(new):
            raise OSError("模拟清理中断")
        return real_clean(source, *args)
    monkeypatch.setattr(moves, "_clean_source", fail)
    conflict = SimpleNamespace(id="c")
    with pytest.raises(OSError, match="清理中断"):
        await service._resolve_local_merge(conflict, session, {}, MergeJournal("c"))
    assert MergeJournal("c").record["state"] == "cleaning"
    assert (old / "a").read_bytes() == b"new"
    monkeypatch.setattr(moves, "_clean_source", real_clean)
    monkeypatch.setattr(plans, "populate_plan", Mock(side_effect=AssertionError("禁止重建")))
    monkeypatch.setattr(moves, "move_path_replacing_sync", Mock(side_effect=AssertionError("禁止重发")))
    result = await resolution.ConflictResolutionService().resolve_merge(conflict, None, {})
    assert result["outcome"] == "merged" and not new.exists()
    assert {p.name for p in old.iterdir()} == {"a", "b"}


def test_replacement_binds_original_inventory(roots, tmp_path):
    new, old = roots
    (old / "a").write_bytes(b"old")
    expected = moves.snapshot(old)
    (old / "a").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="库存已变化"):
        moves.move_path_replacing_sync(str(new), str(old), expected_destination_manifest=expected)
    assert (old / "a").read_bytes() == b"changed"


@pytest.mark.parametrize("failure", ["copy", "sync", "cancel"])
def test_failed_build_preserves_inventory_and_source(roots, tmp_path, monkeypatch, failure):
    import asyncio
    import builtins
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "b").write_bytes(b"old")
    plan = plan_for(new, old)
    destination = tmp_path / "failed-stage"
    destination.mkdir()
    if failure == "sync":
        monkeypatch.setattr(plans.os, "fsync", Mock(side_effect=OSError("同步失败")))
    elif failure == "cancel":
        monkeypatch.setattr(plans, "_check_scope", Mock(side_effect=asyncio.CancelledError()))
    else:
        original = builtins.open
        def opening(path, mode="r", *args, **kwargs):
            if mode == "xb":
                raise OSError("复制失败")
            return original(path, mode, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", opening)
    with pytest.raises((OSError, asyncio.CancelledError)):
        plans.populate_plan(plan, str(destination))
    assert (new / "a").read_bytes() == b"new"
    assert (old / "b").read_bytes() == b"old"


@pytest.mark.asyncio
async def test_index_failure_retries_without_republishing(roots, tmp_path, monkeypatch):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "b").write_bytes(b"old")
    session = resolution.ConflictMergeSession("s", "index-failure", str(tmp_path / "workspace"),
        str(new), str(old), "lib", "local", FolderCompareService().build_compare_items(str(new), str(old)),
        0, source_is_staged=True, cleanup_sources={str(new): moves.snapshot(new)})
    service = resolution.ConflictResolutionService()
    service._notify_index_after_conflict_resolution = Mock(side_effect=OSError("索引通知失败"))
    @asynccontextmanager
    async def acquire(*args, **kwargs):
        yield
    monkeypatch.setattr(resolution, "get_resource_budget_service", lambda: SimpleNamespace(acquire=acquire))
    conflict = SimpleNamespace(id="index-failure")
    with pytest.raises(OSError, match="索引通知失败"):
        await service._resolve_local_merge(conflict, session, {}, MergeJournal(conflict.id))
    assert MergeJournal(conflict.id).record["state"] == "published"
    assert new.exists() and (old / "a").read_bytes() == b"new"
    monkeypatch.setattr(plans, "populate_plan", Mock(side_effect=AssertionError("禁止重建")))
    monkeypatch.setattr(moves, "move_path_replacing_sync", Mock(side_effect=AssertionError("禁止重发")))
    service._notify_index_after_conflict_resolution = Mock()
    result = await service.resolve_merge(conflict, None, {})
    assert result["outcome"] == "merged" and not new.exists()
    service._notify_index_after_conflict_resolution.assert_called_once_with("lib", str(old), str(old), strict=True)


@pytest.mark.parametrize("window", ["backup", "publish"])
@pytest.mark.asyncio
async def test_restart_at_replacement_windows(roots, tmp_path, monkeypatch, window):
    new, old = roots
    (new / "a").write_bytes(b"new")
    (old / "b").write_bytes(b"old")
    session = resolution.ConflictMergeSession("s", window, str(tmp_path / "workspace"), str(new), str(old),
        "lib", "local", FolderCompareService().build_compare_items(str(new), str(old)), 0,
        source_is_staged=True, cleanup_sources={str(new): moves.snapshot(new)})
    service = resolution.ConflictResolutionService()
    service._notify_index_after_conflict_resolution = Mock()
    @asynccontextmanager
    async def acquire(*args, **kwargs):
        yield
    monkeypatch.setattr(resolution, "get_resource_budget_service", lambda: SimpleNamespace(acquire=acquire))
    original = moves.publish_path
    injected = [False]
    def publish(source, target, *args, **kwargs):
        original(source, target, *args, **kwargs)
        matches = source == str(old) if window == "backup" else target == str(old)
        if matches and not injected[0]:
            injected[0] = True
            raise OSError("模拟发布窗口中断")
    monkeypatch.setattr(moves, "publish_path", publish)
    conflict = SimpleNamespace(id=window)
    with pytest.raises((OSError, moves.MoveCleanupPending)):
        await service._resolve_local_merge(conflict, session, {}, MergeJournal(window))
    assert new.exists()
    monkeypatch.setattr(moves, "publish_path", original)
    monkeypatch.setattr(plans, "populate_plan", Mock(side_effect=AssertionError("禁止重建")))
    result = await service.resolve_merge(conflict, None, {})
    assert result["outcome"] == "merged"
    assert {p.name for p in old.iterdir()} == {"a", "b"}
    assert not new.exists()


def test_host_clone_failure_does_not_fallback(roots, tmp_path, monkeypatch):
    new, old = roots
    (new / "a").write_bytes(b"new")
    plan = plan_for(new, old)
    config = SimpleNamespace(host_enabled=True, socket_path="test", request_timeout_seconds=1)
    monkeypatch.setattr(plans, "move_config", lambda: config)
    client = Mock()
    client.probe.return_value = {"same_filesystem": True, "capabilities": ["multi_source_directory_v1"], "mapping_version": "v1"}
    def request(action, **kwargs):
        if action == "prepare_multi_member":
            raise RuntimeError("克隆失败")
        return {}
    client.request.side_effect = request
    monkeypatch.setattr(plans, "HostMoveClient", Mock(return_value=client))
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(RuntimeError, match="克隆失败"):
        plans.populate_plan(plan, str(stage))
    assert not (stage / "a").exists()
    assert (new / "a").read_bytes() == b"new"
    assert client.request.call_args.args == ("cancel",)
