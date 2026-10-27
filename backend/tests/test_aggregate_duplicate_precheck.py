"""合集在完整解压前按所有 RJ 判重，并保留整包身份。"""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.classifier import SmartClassifier
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


CODES = ["RJ01385196", "RJ01416572"]


@pytest.fixture
def precheck(tmp_path, monkeypatch):
    source = tmp_path / "合集.rar"
    source.write_bytes(b"archive")
    task = Task(TaskType.AUTO_PROCESS, str(source), auto_classify=True)
    engine = TaskEngine()
    monkeypatch.setattr(Task, "_global_event_hook", None)
    monkeypatch.setattr(engine, "mark_rjcode_processing", Mock())
    service = SimpleNamespace(
        lookup_filename_bound_rjcode=AsyncMock(return_value=None),
        infer_rjcode_from_archive=AsyncMock(return_value=None),
        collect_top_level_rjcodes=AsyncMock(return_value=CODES),
        extract=AsyncMock(side_effect=RuntimeError("密码错误")),
    )
    config = SimpleNamespace(auto_process=SimpleNamespace(
        check_duplicate=True, import_linked_translation_subtitles=True, extract=True,
    ))
    classifier = SmartClassifier(prepared_conflicts=[])
    classifier.check_duplicate_before_extract = AsyncMock()
    query = Mock(return_value={code: [{
        "path": f"/library/{code}", "library_id": "local", "library_name": "库存",
    }] for code in CODES})
    monkeypatch.setattr("app.core.classifier.get_library_manager", lambda: SimpleNamespace(
        find_rj_in_ready_index=query,
    ))
    yield SimpleNamespace(
        task=task, engine=engine, service=service, config=config,
        classifier=classifier, query=query,
    )
    engine.stop()


async def run_precheck(ctx):
    return await ctx.engine._preflight_auto_process(
        ctx.task, ctx.service, ctx.classifier, ctx.config,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["合集.rar", "RJ01385196 合集.rar"])
async def test_all_owned_stops_before_extract_with_one_aggregate_conflict(precheck, filename):
    ctx = precheck
    source = ctx.task.source_path
    if Path(source).name != filename:
        Path(source).rename(Path(source).with_name(filename))
    ctx.task.source_path = str(Path(source).with_name(filename))
    ctx.task._prepared_conflicts = ctx.classifier.prepared_conflicts

    rjcode, proceed = await run_precheck(ctx)

    assert (rjcode, proceed) == ("", False)
    assert ctx.task.status == TaskStatus.WAITING_MANUAL
    assert ctx.task.completed_at is not None
    assert ctx.task.rjcode is None
    assert len(ctx.task._prepared_conflicts) == 1
    conflict = ctx.task._prepared_conflicts[0]
    assert conflict.conflict_type == "DUPLICATE"
    assert conflict.rjcode is None
    assert conflict.new_path == ctx.task.source_path
    assert conflict.existing_path == ""
    assert conflict.related_rjcodes == CODES
    assert {hit["rjcode"] for hit in conflict.linked_works_info} == set(CODES)
    assert conflict.new_metadata["available_actions"] == ["SKIP"]
    assert conflict.new_metadata["aggregate_rjcodes"] == CODES
    assert conflict.new_metadata["work_name"] == f"{filename}（2 个作品）"
    ctx.query.assert_called_once_with(CODES, include_subtitle_state=False)
    ctx.engine.mark_rjcode_processing.assert_not_called()
    ctx.classifier.check_duplicate_before_extract.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [[], CODES[:1], CODES[1:]])
async def test_partial_or_missing_works_continue_without_parent_conflicts(precheck, owned):
    ctx = precheck
    ctx.query.return_value = {
        code: [{"path": f"/library/{code}"}] for code in owned
    }

    assert await run_precheck(ctx) == ("", True)

    assert ctx.task.rjcode is None
    assert ctx.classifier.prepared_conflicts == []
    assert ctx.task.task_metadata["aggregate_duplicate_precheck"]["matched_rjcodes"] == owned
    assert ctx.task.task_metadata["aggregate_duplicate_precheck"]["missing_rjcodes"] == [
        code for code in CODES if code not in owned
    ]
    ctx.engine.mark_rjcode_processing.assert_not_called()
    ctx.classifier.check_duplicate_before_extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_error_is_not_treated_as_successful_precheck(precheck):
    ctx = precheck
    ctx.query.side_effect = RuntimeError("库存查询失败")

    with pytest.raises(RuntimeError, match="库存查询失败"):
        await run_precheck(ctx)

    assert ctx.classifier.prepared_conflicts == []
    assert "aggregate_duplicate_precheck" not in ctx.task.task_metadata


@pytest.mark.asyncio
async def test_multiple_locations_for_one_rj_cannot_count_as_all_works(precheck):
    ctx = precheck
    ctx.query.return_value = {
        CODES[0]: [{"path": "/library/a"}, {"path": "/library/b"}],
        CODES[1]: [{"path": ""}],
    }

    assert await run_precheck(ctx) == ("", True)
    assert ctx.classifier.prepared_conflicts == []
    assert ctx.task.task_metadata["aggregate_duplicate_precheck"]["missing_rjcodes"] == CODES[1:]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "unclassified", "manual_retry"])
async def test_respects_duplicate_policy_and_confirmed_manual_actions(precheck, mode):
    ctx = precheck
    if mode == "disabled":
        ctx.config.auto_process.check_duplicate = False
    elif mode == "unclassified":
        ctx.task.auto_classify = False
    else:
        ctx.task.task_metadata.update({
            "skip_retry_precheck": True, "conflict_resolution_action": "KEEP_NEW",
        })

    _, proceed = await run_precheck(ctx)

    assert proceed
    ctx.query.assert_not_called()
    assert ctx.classifier.prepared_conflicts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [CODES, CODES[:1]])
async def test_consumed_scan_evidence_rechecks_current_aggregate_inventory(
    precheck, monkeypatch, owned,
):
    ctx = precheck
    ctx.task.task_metadata.update({
        "aggregate_archive": True, "aggregate_rjcodes": CODES,
        "input_preflight": {"rjcode": "", "proceed": True},
        "rjcode": CODES[0], "inferred_rjcode": CODES[0],
    })
    ctx.task.rjcode = CODES[0]
    ctx.query.return_value = {code: [{"path": f"/library/{code}"}] for code in owned}

    @asynccontextmanager
    async def acquire(*_args, **_kwargs):
        yield

    monkeypatch.setattr("app.core.input_preflight.can_consume", lambda *_args: True)
    monkeypatch.setattr(
        "app.core.resource_budget_service.get_resource_budget_service",
        lambda: SimpleNamespace(acquire=acquire),
    )

    rjcode, proceed = await run_precheck(ctx)

    assert rjcode == ""
    assert ctx.task.rjcode is None
    assert "rjcode" not in ctx.task.task_metadata
    assert "inferred_rjcode" not in ctx.task.task_metadata
    assert proceed == (len(owned) < len(CODES))
    assert len(ctx.classifier.prepared_conflicts) == (not proceed)
    ctx.query.assert_called_once_with(CODES, include_subtitle_state=False)
    ctx.service.collect_top_level_rjcodes.assert_not_awaited()
    ctx.classifier.check_duplicate_before_extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumed_aggregate_never_reverts_to_first_rj_check(precheck, monkeypatch):
    ctx = precheck
    ctx.config.auto_process.check_duplicate = False
    ctx.task.task_metadata.update({
        "aggregate_archive": True, "aggregate_rjcodes": CODES,
        "input_preflight": {"rjcode": CODES[0], "proceed": True},
        "preflight_runtime_duplicate_check": True,
    })

    @asynccontextmanager
    async def acquire(*_args, **_kwargs):
        yield

    monkeypatch.setattr("app.core.input_preflight.can_consume", lambda *_args: True)
    monkeypatch.setattr(
        "app.core.resource_budget_service.get_resource_budget_service",
        lambda: SimpleNamespace(acquire=acquire),
    )

    assert await run_precheck(ctx) == ("", True)
    ctx.query.assert_not_called()
    ctx.classifier.check_duplicate_before_extract.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_single_work_retains_original_duplicate_precheck(precheck, duplicate):
    ctx = precheck
    ctx.task.source_path = str(Path(ctx.task.source_path).rename(
        Path(ctx.task.source_path).with_name(f"{CODES[0]}.rar"),
    ))
    ctx.service.collect_top_level_rjcodes.return_value = CODES[:1]
    ctx.config.auto_process.import_linked_translation_subtitles = False
    ctx.classifier.check_duplicate_before_extract.return_value = duplicate

    assert await run_precheck(ctx) == (CODES[0], not duplicate)
    ctx.classifier.check_duplicate_before_extract.assert_awaited_once_with(
        CODES[0], ctx.task, ctx.engine,
    )
    ctx.query.assert_not_called()
    assert ctx.classifier.prepared_conflicts == []


@pytest.mark.asyncio
async def test_all_owned_never_reaches_password_extraction(precheck, monkeypatch):
    ctx = precheck
    monkeypatch.setattr("app.config.settings.get_config", lambda: ctx.config)
    monkeypatch.setattr("app.core.extract_service.ExtractService", lambda: ctx.service)
    monkeypatch.setattr("app.core.classifier.SmartClassifier", lambda: ctx.classifier)
    for name in ["_notify_progress", "_cleanup_task_temp_extract_path", "_cleanup_failed_task"]:
        monkeypatch.setattr(ctx.engine, name, AsyncMock())
    for name in [
        "persist_task_center_item_snapshot", "_record_problem_work_for_task_failure",
        "_resolve_retry_extract_conflict", "_resolve_completed_failure_followups",
        "_finalize_conflict_resolution_task", "_refresh_conflict_resolution_progress",
        "unmark_rjcode_processing",
    ]:
        monkeypatch.setattr(ctx.engine, name, Mock())
    monkeypatch.setattr("app.core.activity_log_service.log_task_lifecycle_event", Mock())
    monkeypatch.setattr("app.core.task_notification_service.enqueue_notification_check", AsyncMock())

    await ctx.engine._process_task(ctx.task)

    assert ctx.task.status == TaskStatus.WAITING_MANUAL
    ctx.service.extract.assert_not_awaited()
    assert [item.conflict_type for item in ctx.classifier.prepared_conflicts] == ["DUPLICATE"]
    ctx.engine._record_problem_work_for_task_failure.assert_not_called()
