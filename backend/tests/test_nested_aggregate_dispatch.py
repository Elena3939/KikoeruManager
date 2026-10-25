"""嵌套合集保留作品目录，拆分后分别执行关联查重。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import zipfile

import pytest

from app.core.extract_service import ExtractService
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


CODES = ["RJ01410151", "RJ01428862"]


@pytest.mark.asyncio
async def test_dispatch_failure_preserves_moved_payload(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(
        storage=SimpleNamespace(temp_path=str(tmp_path)),
        file_move=settings.FileMoveConfig(journal_path=str(tmp_path / "moves")),
    ))
    monkeypatch.setattr(Task, "_global_event_hook", None)
    engine = TaskEngine(max_concurrent=1)
    source = tmp_path / CODES[0]
    source.mkdir()
    (source / "track.wav").write_bytes(b"audio")
    parent = Task(TaskType.AUTO_PROCESS, "Share.zip")
    monkeypatch.setattr(engine, "submit", AsyncMock(side_effect=RuntimeError("提交失败")))
    try:
        assert await engine._dispatch_multi_rj_subtasks(parent, str(tmp_path), [
            {"rjcode": CODES[0], "path": str(source)},
        ]) == []
        failed = parent.task_metadata["multi_rj_dispatch_failures"][0]
        assert (Path(failed["path"]) / "track.wav").read_bytes() == b"audio"
    finally:
        engine.stop()


@pytest.fixture
def isolated_engine(monkeypatch):
    engine = TaskEngine(max_concurrent=1)
    for name in [
        "_notify_progress", "_cleanup_task_temp_extract_path", "_cleanup_failed_task",
    ]:
        monkeypatch.setattr(engine, name, AsyncMock())
    for name in [
        "persist_task_center_item_snapshot", "_record_problem_work_for_task_failure",
        "_resolve_retry_extract_conflict", "_resolve_completed_failure_followups",
        "_finalize_conflict_resolution_task", "_refresh_conflict_resolution_progress",
        "unmark_rjcode_processing",
    ]:
        monkeypatch.setattr(engine, name, Mock())
    monkeypatch.setattr("app.core.activity_log_service.log_task_lifecycle_event", Mock())
    monkeypatch.setattr("app.core.task_notification_service.enqueue_notification_check", AsyncMock())
    monkeypatch.setattr("app.core.notification_helper.build_import_notification_extra", Mock(return_value={}))
    monkeypatch.setattr("app.core.notification_helper._load_circle_work_map", Mock(return_value={}))
    return engine


@pytest.mark.asyncio
async def test_nested_original_and_bonus_keep_separate_payloads_and_dispatch(
    tmp_path, monkeypatch, isolated_engine,
):
    from app.config import settings

    output = tmp_path / "Share"
    output.mkdir()
    payloads = ["作品名/wav/track.wav", "早期特典/BonusTrack/track.wav"]
    for code, name in zip(CODES, payloads):
        with zipfile.ZipFile(output / f"{code}.zip", "w") as archive:
            archive.writestr(name, code.encode())
    source = tmp_path / "Share.zip"
    source.write_bytes(b"outer archive")
    service = ExtractService()
    parent = Task(TaskType.AUTO_PROCESS, str(source), auto_classify=True, metadata={
        "aggregate_archive": True, "aggregate_rjcodes": CODES,
        "scan_id": "scan-parent", "candidate_id": "candidate-parent",
        "input_stability": {"parent_only": True},
    })

    async def extract_inner(archive_path, output_path, *_args, **_kwargs):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(output_path)
        return True, ""

    monkeypatch.setattr(service, "_try_extract_nested_direct", AsyncMock(side_effect=extract_inner))
    monkeypatch.setattr(service, "_classify_nested_small_archive", AsyncMock(return_value="content"))
    count = await service._extract_nested_archives(str(output), parent, max_depth=3)
    assert count == 2
    assert not list(output.glob("*.zip"))
    for code, name in zip(CODES, payloads):
        assert (output / code / name).read_bytes() == code.encode()

    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(
        storage=SimpleNamespace(temp_path=str(tmp_path)),
        file_move=settings.FileMoveConfig(journal_path=str(tmp_path / "file-moves")),
    ))
    submitted = []

    async def submit(task):
        submitted.append(task)
        return task.id

    monkeypatch.setattr(isolated_engine, "submit", submit)
    directories = isolated_engine._detect_multi_rj_subfolders(str(output))
    assert {entry["rjcode"] for entry in directories} == set(CODES)
    ids = await isolated_engine._dispatch_multi_rj_subtasks(parent, str(output), directories)
    assert len(ids) == 2
    for child in submitted:
        index = CODES.index(child.rjcode)
        assert child.type == TaskType.PROCESS_EXISTING_FOLDER
        assert child.auto_classify is True
        assert child.task_metadata["rjcode_lock"] is True
        assert child.task_metadata["scan_id"] == "scan-parent"
        assert child.task_metadata["candidate_id"] == "candidate-parent"
        assert "input_stability" not in child.task_metadata
        assert (Path(child.source_path) / payloads[index]).read_bytes() == child.rjcode.encode()
        other = payloads[1 - index]
        assert not (Path(child.source_path) / other).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["no_rj", "one_rj", "wrong_rj", "dispatch_failed"])
async def test_known_aggregate_cannot_enter_single_work_pipeline(
    tmp_path, monkeypatch, isolated_engine, layout,
):
    from app.config import settings

    source = tmp_path / "Share.zip"
    source.write_bytes(b"archive")
    output = tmp_path / "Share"
    output.mkdir()
    names = {
        "no_rj": ["作品名", "早期特典"],
        "one_rj": [CODES[0]],
        "wrong_rj": [CODES[0], "RJ99999999"],
        "dispatch_failed": CODES,
    }[layout]
    for name in names:
        (output / name).mkdir()
        (output / name / "track.wav").write_bytes(b"audio")
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(
        auto_process=SimpleNamespace(extract=True),
    ))
    monkeypatch.setattr("app.core.extract_service.ExtractService", lambda: SimpleNamespace(
        extract=AsyncMock(return_value=str(output)),
    ))
    fetch = AsyncMock()
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: SimpleNamespace(fetch=fetch))
    classifier = Mock()
    monkeypatch.setattr("app.core.classifier.SmartClassifier", lambda: classifier)
    monkeypatch.setattr(isolated_engine, "_should_skip_conflict_retry_precheck", lambda _task: True)
    monkeypatch.setattr(isolated_engine, "_dispatch_multi_rj_subtasks", AsyncMock(return_value=[]))
    archive = AsyncMock()
    monkeypatch.setattr(isolated_engine, "_archive_source_file", archive)
    task = Task(TaskType.AUTO_PROCESS, str(source), metadata={
        "aggregate_archive": True, "aggregate_rjcodes": CODES,
    })

    await isolated_engine._process_task(task)

    assert task.status == TaskStatus.FAILED
    assert task.task_metadata["failure_stage"] == "extract"
    assert "合集作品拆分失败" in task.error_message
    assert source.exists()
    fetch.assert_not_awaited()
    classifier.classify_and_move.assert_not_called()
    archive.assert_not_awaited()
    if layout == "dispatch_failed":
        isolated_engine._dispatch_multi_rj_subtasks.assert_awaited_once()
    else:
        isolated_engine._dispatch_multi_rj_subtasks.assert_not_awaited()
    isolated_engine._record_problem_work_for_task_failure.assert_called_once()


@pytest.mark.asyncio
async def test_split_original_detects_existing_translation_before_metadata(
    tmp_path, monkeypatch, isolated_engine,
):
    from app.config import settings

    source = tmp_path / CODES[0]
    source.mkdir()
    monkeypatch.setattr(settings, "get_config", lambda: SimpleNamespace(
        process_existing=SimpleNamespace(check_duplicate=True, filter=False, classify=True),
    ))
    duplicate = SimpleNamespace(
        is_duplicate=True, conflict_type="LINKED_WORK", direct_duplicate=None,
        linked_works_found=[{"rjcode": "RJ01561460", "path": "/library/RJ01561460"}],
        analysis_info={}, related_rjcodes=["RJ01561460"],
    )
    check = AsyncMock(return_value=duplicate)
    monkeypatch.setattr("app.core.duplicate_service.get_duplicate_service", lambda: SimpleNamespace(
        check_duplicate_enhanced=check,
    ))
    fetch = AsyncMock()
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: SimpleNamespace(fetch=fetch))
    classifier = Mock()
    monkeypatch.setattr("app.core.classifier.SmartClassifier", lambda: classifier)
    monkeypatch.setattr(isolated_engine, "_stabilize_extract_subtask_conflict_source", AsyncMock(return_value=str(source)))
    task = Task(TaskType.PROCESS_EXISTING_FOLDER, str(source), auto_classify=True, rjcode=CODES[0], metadata={
        "rjcode": CODES[0], "rjcode_lock": True, "is_extract_subtask": True,
    })

    await isolated_engine._process_task(task)

    assert task.status == TaskStatus.WAITING_MANUAL
    check.assert_awaited_once_with(
        CODES[0], check_linked_works=True, cue_languages=["CHI_HANS", "CHI_HANT", "ENG"],
    )
    args = classifier._add_to_conflict_works.call_args
    assert args.args[1:4] == (CODES[0], "LINKED_WORK", "/library/RJ01561460")
    assert args.kwargs["linked_works_info"] == duplicate.linked_works_found
    fetch.assert_not_awaited()
