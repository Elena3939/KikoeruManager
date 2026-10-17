from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.conflict_resolution_service import ConflictResolutionService


def conflict(path="正在处理中", **metadata):
    return SimpleNamespace(
        id="pending-conflict", existing_path=path, new_path="source.7z",
        new_metadata=metadata, rjcode="RJ01731933", status="PENDING",
        conflict_type="DUPLICATE",
    )


@pytest.fixture
def context():
    service = ConflictResolutionService()
    manager = Mock()
    manager.find_rj_in_ready_index.return_value = {}
    with patch("app.core.conflict_resolution_service.get_library_manager", return_value=manager), patch.object(
        service, "_iter_libraries", return_value=[],
    ):
        yield service, manager


def test_waiting_label_is_not_a_merge_target_even_with_stored_actions(context):
    service, manager = context
    item = conflict(available_actions=["KEEP_NEW", "MERGE", "SKIP"])
    assert service.describe_conflict(item)["existing"]["path"] == ""
    assert service.get_available_actions(item) == ["KEEP_NEW", "SKIP"]
    manager.find_rj_in_libraries.assert_not_called()


def test_unique_ready_directory_restores_merge_target(context, tmp_path):
    service, manager = context
    target = tmp_path / "RJ01731933"
    target.mkdir()
    manager.find_rj_in_ready_index.return_value = {"RJ01731933": [{"path": str(target)}]}
    assert service.describe_conflict(conflict())["existing"]["path"] == str(target)
    assert "MERGE" in service.get_available_actions(conflict())


def test_multiple_directories_are_not_arbitrarily_merged(context, tmp_path):
    service, manager = context
    targets = [tmp_path / "first", tmp_path / "second"]
    for target in targets:
        target.mkdir()
    manager.find_rj_in_ready_index.return_value = {"RJ01731933": [{"path": str(p)} for p in targets]}
    existing = service.describe_conflict(conflict())["existing"]
    assert existing["path"] == ""
    assert "多个库存" in existing["unavailable_reason"]
    assert service.get_available_actions(conflict()) == ["MERGE", "SKIP"]


@pytest.mark.asyncio
async def test_multiple_targets_require_selection_before_starting_job(context, tmp_path):
    service, manager = context
    targets = [tmp_path / "first", tmp_path / "second"]
    for target in targets:
        target.mkdir()
    manager.find_rj_in_ready_index.return_value = {"RJ01731933": [{"path": str(p)} for p in targets]}
    with patch.object(service, "_resolve_conflict_new_path", return_value="source.7z"), patch.object(
        service, "_run_merge_preview_worker", new_callable=AsyncMock,
    ) as worker:
        response = await service.start_merge_preview(conflict())
        assert response["requires_target_selection"] is True
        assert len(response["target_candidates"]) == 2
        assert not service._merge_preview_jobs
        selected = response["target_candidates"][1]
        job = await service.start_merge_preview(conflict(), selected)
        assert service._merge_preview_jobs[job["job_id"]].target_context["path"] == str(targets[1])
        await service._merge_preview_workers[job["job_id"]]
        worker.assert_awaited_once()


def test_selected_target_must_be_one_of_current_candidates(context, tmp_path):
    service, _ = context
    with pytest.raises(ValueError, match="目标已失效"):
        service._select_merge_target(
            {"target_candidates": [{"path": str(tmp_path / "real"), "library_id": "library"}]},
            {"path": str(tmp_path / "arbitrary"), "library_id": "library"},
        )


def test_stale_index_hit_does_not_become_target(context, tmp_path):
    service, manager = context
    manager.find_rj_in_ready_index.return_value = {"RJ01731933": [{"path": str(tmp_path / "missing")}]}
    assert service.describe_conflict(conflict())["existing"]["path"] == ""


@pytest.mark.parametrize("include_root", [True, False])
def test_inherited_rj_subdirectories_resolve_to_one_work_root(context, tmp_path, include_root):
    service, manager = context
    root = tmp_path / "社团" / "作品[RJ01731933][CV 小花衣こここ]"
    children = [root / "PICTURE", root / "TEXT", root / "TEXT" / "02_台本"]
    for child in children:
        child.mkdir(parents=True, exist_ok=True)
    # 子目录先到、根目录最后到，以及索引仅返回子目录，都不能产生多个目标。
    paths = children + ([root] if include_root else [])
    manager.find_rj_in_ready_index.return_value = {
        "RJ01731933": [{"path": str(p), "library_root_path": str(tmp_path)} for p in paths],
    }
    existing = service.describe_conflict(conflict())["existing"]
    assert existing["path"] == str(root)
    assert not existing.get("target_candidates")


def test_distinct_work_roots_keep_user_selection(context, tmp_path):
    service, manager = context
    roots = [tmp_path / "作品[RJ01731933]", tmp_path / "作品[RJ01731933]-另一版"]
    paths = []
    for root in roots:
        child = root / "TEXT"
        child.mkdir(parents=True)
        paths.extend([child, root])
    manager.find_rj_in_ready_index.return_value = {
        "RJ01731933": [{"path": str(p)} for p in paths],
    }
    existing = service.describe_conflict(conflict())["existing"]
    assert existing["path"] == ""
    assert {p["path"] for p in existing["target_candidates"]} == {str(p) for p in roots}


@pytest.mark.parametrize("nested", ["RJ12345678", "合集[RJ01731933][RJ12345678]"])
def test_other_work_or_collection_is_not_an_inherited_target(context, tmp_path, nested):
    service, manager = context
    root = tmp_path / "RJ01731933"
    unrelated = root / nested / "TEXT"
    unrelated.mkdir(parents=True)
    manager.find_rj_in_ready_index.return_value = {"RJ01731933": [{"path": str(unrelated)}]}
    assert service.describe_conflict(conflict())["existing"]["path"] == ""


def test_library_root_rj_is_not_treated_as_work(context, tmp_path):
    service, manager = context
    library = tmp_path / "RJ01731933"
    work = library / "分类" / "实际作品"
    work.mkdir(parents=True)
    manager.find_rj_in_ready_index.return_value = {
        "RJ01731933": [{"path": str(work), "library_root_path": str(library)}],
    }
    assert service.describe_conflict(conflict())["existing"]["path"] == str(work)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["create_merge_preview", "start_merge_preview"])
async def test_missing_target_fails_before_workspace_or_extract(context, tmp_path, entry):
    service, _ = context
    item = conflict(str(tmp_path / "missing"))
    with patch.object(service, "_resolve_conflict_new_path", return_value=item.new_path), patch.object(
        service, "_create_workspace",
    ) as workspace, patch.object(service, "_stage_new_source", new_callable=AsyncMock) as extract:
        with pytest.raises(FileNotFoundError, match="合并目标目录不存在"):
            await getattr(service, entry)(item)
    workspace.assert_not_called()
    extract.assert_not_called()


@pytest.mark.asyncio
async def test_waiting_target_error_explains_reimport_action(context):
    service, _ = context
    with patch.object(service, "_resolve_conflict_new_path", return_value="source.7z"):
        with pytest.raises(RuntimeError, match="保留新版重新入库"):
            await service.start_merge_preview(conflict())
