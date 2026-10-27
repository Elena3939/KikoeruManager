from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api import routes as routes_module
from app.config import settings as settings_module
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType
from app.models import database as database_module


@pytest.fixture
def engine():
    return TaskEngine(max_concurrent=2)


def test_rename_failure_checkpoint_keeps_extracted_directory_for_retry(engine, tmp_path):
    source = tmp_path / "RJ01630001.zip"
    source.write_bytes(b"archive")
    extracted = tmp_path / "extract" / "RJ01630001"
    extracted.mkdir(parents=True)
    task = Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path=str(source),
        auto_classify=True,
        metadata={"rjcode": "RJ01630001", "work_name": "测试作品"},
    )

    engine._mark_rename_failure_checkpoint(
        task,
        str(extracted),
        archive_source_path=str(source),
        archive_enabled=True,
        filter_enabled=True,
        classify_enabled=True,
    )

    assert task.output_path == str(extracted)
    assert task.task_metadata["failure_stage"] == "rename"
    assert task.task_metadata["resume_from_stage"] == "rename"
    assert task.task_metadata["rename_retry_source_path"] == str(extracted)
    assert task.task_metadata["rename_retry_archive_source_path"] == str(source)
    assert task.task_metadata["rename_retry_archive_enabled"] is True
    assert task.task_metadata["rename_retry_filter_enabled"] is True
    assert task.task_metadata["rename_retry_classify_enabled"] is True


def test_rename_failure_problem_uses_checkpoint_path(engine, tmp_path):
    source = tmp_path / "RJ01630002.zip"
    source.write_bytes(b"archive")
    extracted = tmp_path / "extract" / "RJ01630002"
    extracted.mkdir(parents=True)
    task = Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path=str(source),
        auto_classify=True,
        metadata={"rjcode": "RJ01630002", "work_name": "测试作品"},
    )
    task.current_step = "重命名文件夹"
    engine._mark_rename_failure_checkpoint(task, str(extracted))

    with patch("app.core.classifier.SmartClassifier._add_to_conflict_works") as add_conflict:
        engine._record_problem_work_for_task_failure(task, "RJ01630002", "目录被占用")

    assert task.task_metadata["failure_stage"] == "rename"
    assert task.task_metadata["retry_source_path"] == str(extracted)
    assert add_conflict.call_args.args[4] == str(extracted)
    assert add_conflict.call_args.args[5]["source_task_type"] == TaskType.AUTO_PROCESS.value


@pytest.mark.asyncio
async def test_cleanup_failed_task_preserves_rename_checkpoint(engine, tmp_path, monkeypatch):
    source = tmp_path / "RJ01630004.zip"
    source.write_bytes(b"archive")
    extracted = tmp_path / "extract" / "RJ01630004"
    extracted.mkdir(parents=True)
    (extracted / "track.mp3").write_bytes(b"audio")
    task = Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path=str(source),
        auto_classify=True,
        metadata={"rjcode": "RJ01630004"},
    )
    engine._mark_rename_failure_checkpoint(task, str(extracted))
    task.fail("目录被占用")
    monkeypatch.setattr(settings_module, "get_config", lambda: SimpleNamespace())

    await engine._cleanup_failed_task(task)

    assert extracted.is_dir()
    assert (extracted / "track.mp3").is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["rename", "metadata", "metadata_failed", "linkage", "linkage_failed"])
async def test_retry_resumes_at_failed_stage(engine, tmp_path, monkeypatch, stage):
    extracted = tmp_path / "RJ01630003"
    extracted.mkdir()
    task = Task(
        task_type=TaskType.PROCESS_EXISTING_FOLDER,
        source_path=str(extracted),
        auto_classify=True,
        metadata={
            "rjcode": "RJ01630003",
            "work_name": "断点重试作品",
            "metadata_evidence_source": "dlsite_product",
            "maker_name": "测试社团",
            "resume_from_stage": {"metadata_failed": "metadata", "linkage_failed": "linkage"}.get(stage, stage),
            "retry_from_conflicts": True,
            "skip_duplicate_precheck": not stage.startswith("linkage"),
            "retry_linkage_required": stage.startswith("linkage"),
            "rename_retry_filter_enabled": False,
            "rename_retry_classify_enabled": True,
        },
        rjcode="RJ01630003",
    )
    config = SimpleNamespace(
        process_existing=SimpleNamespace(
            check_duplicate=True,
            fetch_metadata=True,
            rename=False,
            filter=False,
            import_lrc=False,
            classify=False,
        ),
        rename=SimpleNamespace(
            flatten_single_subfolder=False,
            remove_empty_folders=False,
        ),
        asmr_sync=SimpleNamespace(simplify_chinese_enabled=False),
        storage=SimpleNamespace(asmr_subtitle_path=""),
    )
    monkeypatch.setattr(settings_module, "get_config", lambda: config)

    rename_calls = []
    classify_calls = []

    fetch_calls = []

    class FakeMetadataService:
        async def fetch(self, *_args, **kwargs):
            assert stage in {"metadata", "metadata_failed", "linkage"}, "纯重命名失败应复用有效数据"
            fetch_calls.append(kwargs)
            if stage == "metadata_failed":
                return {"rjcode": "RJ01630003", "work_name": "RJ01630003", "metadata_source": "minimal"}
            return {"rjcode": "RJ01630003", "work_name": "断点重试作品", "maker_name": "测试社团", "metadata_evidence_source": "dlsite_product"}

    class FakeRenameService:
        async def rename(self, path, _task):
            rename_calls.append(path)
            return path

    class FakeClassifier:
        async def check_duplicate_before_extract(self, *_args):
            return False

        async def classify_and_move(self, path, metadata, _task):
            classify_calls.append((path, dict(metadata)))
            return path

    monkeypatch.setattr("app.core.metadata_service.MetadataService", FakeMetadataService)
    monkeypatch.setattr("app.core.rename_service.RenameService", FakeRenameService)
    monkeypatch.setattr("app.core.classifier.SmartClassifier", FakeClassifier)
    duplicate_check = AsyncMock(return_value=SimpleNamespace(is_duplicate=False))
    if stage == "linkage_failed":
        from app.core.import_validation import ImportDataError
        duplicate_check.side_effect = ImportDataError("关联数据查询失败", "linkage")
    monkeypatch.setattr("app.core.duplicate_service.get_duplicate_service", lambda: SimpleNamespace(check_duplicate_enhanced=duplicate_check))
    monkeypatch.setattr(engine, "_notify_progress", AsyncMock())
    monkeypatch.setattr(engine, "_archive_rename_retry_source", AsyncMock())
    monkeypatch.setattr(engine, "_resolve_retry_extract_conflict", Mock())
    monkeypatch.setattr(engine, "_resolve_completed_failure_followups", Mock())
    monkeypatch.setattr(engine, "_finalize_conflict_resolution_task", Mock())
    monkeypatch.setattr(engine, "_cleanup_task_temp_extract_path", AsyncMock())
    monkeypatch.setattr(engine, "_cleanup_failed_task", AsyncMock())
    monkeypatch.setattr(engine, "persist_task_center_item_snapshot", Mock())
    monkeypatch.setattr(
        "app.core.circle_completion_service.get_circle_completion_service",
        lambda: SimpleNamespace(sync_owned_for_rj=AsyncMock()),
    )
    monkeypatch.setattr("app.core.activity_log_service.log_task_lifecycle_event", Mock())
    monkeypatch.setattr("app.core.task_notification_service.enqueue_notification_check", AsyncMock())

    await engine._process_task(task)

    if stage in {"metadata_failed", "linkage_failed"}:
        assert task.status == TaskStatus.FAILED
        assert rename_calls == []
        assert classify_calls == []
        assert task.output_path == str(extracted)
        assert task.task_metadata["resume_from_stage"] == ("linkage" if stage == "linkage_failed" else "metadata")
        assert task.task_metadata["rename_retry_classify_enabled"] is True
        engine._archive_rename_retry_source.assert_not_awaited()
        return
    assert task.status == TaskStatus.COMPLETED
    assert rename_calls == [str(extracted)]
    assert len(classify_calls) == 1
    assert classify_calls[0][1]["work_name"] == "断点重试作品"
    engine._archive_rename_retry_source.assert_awaited_once_with(task)

    assert bool(fetch_calls) == (stage in {"metadata", "linkage"})
    assert duplicate_check.await_count == (1 if stage == "linkage" else 0)
    if fetch_calls:
        assert fetch_calls[0]["force_refresh"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["rename", "metadata", "linkage", "api_local", "api_remote"])
async def test_conflict_retry_builds_process_existing_task_for_checkpoint(tmp_path, monkeypatch, stage):
    extracted = tmp_path / "RJ01630005"
    extracted.mkdir()
    source = tmp_path / "RJ01630005.zip"
    source.write_bytes(b"archive")
    conflict = SimpleNamespace(
        id="conflict-rename",
        status="PENDING",
        conflict_type="PROCESS_FAILED",
        new_path=str(extracted),
        new_metadata={
            "failure_stage": stage,
            "source_task_type": TaskType.AUTO_PROCESS.value,
            "rjcode": "RJ01630005",
            "work_name": "重命名失败作品",
            "rename_retry_source_path": str(extracted),
            "rename_retry_archive_source_path": str(source),
            "rename_retry_archive_enabled": True,
            "rename_retry_filter_enabled": True,
            "rename_retry_classify_enabled": True,
        },
        task_id="failed-task-id",
        rjcode="RJ01630005",
    )
    if stage.startswith("api_"):
        conflict.new_metadata.pop("rename_retry_source_path")
        conflict.new_metadata.update({
            "failure_stage": "metadata", "source_operation": "api_rename",
            "library_id": "library-a",
            "source_library_type": "synology_filestation" if stage == "api_remote" else "local",
        })
        if stage == "api_remote":
            conflict.new_path = "/remote/RJ01630005"
            conflict.new_metadata["retry_source_path"] = conflict.new_path

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return conflict if self.model is database_module.ConflictWork else None

    class FakeDb:
        def query(self, model, *_args, **_kwargs):
            return FakeQuery(model)

        def commit(self):
            return None

        def close(self):
            return None

    submitted = []
    fake_engine = SimpleNamespace(
        get_all_tasks=lambda: [],
        get_task=lambda _task_id: None,
        cleanup_retry_output_artifacts=Mock(
            side_effect=AssertionError("重命名断点重试不能清理解压产物")
        ),
    )

    async def submit(task):
        submitted.append(task)
        return task.id

    fake_engine.submit = submit
    monkeypatch.setattr(database_module, "get_db", lambda: iter([FakeDb()]))
    monkeypatch.setattr(routes_module, "get_task_engine", lambda: fake_engine)
    monkeypatch.setattr("app.core.input_scan_repository.source_lock", Mock())
    monkeypatch.setattr("app.core.input_scan_repository.handoff_conflict_claims", Mock())
    monkeypatch.setattr("app.core.conflict_retry_activity.log_retry_batch", Mock())

    result = await routes_module.retry_extract_failed_conflict("conflict-rename")

    assert result["success"] is True
    assert len(submitted) == 1
    retry_task = submitted[0]
    assert retry_task.type == (TaskType.RENAME if stage.startswith("api_") else TaskType.PROCESS_EXISTING_FOLDER)
    assert retry_task.source_path == conflict.new_path
    if stage.startswith("api_"):
        assert retry_task.task_metadata["library_id"] == "library-a"
        assert retry_task.task_metadata["rjcode_lock"] is True
    else:
        assert retry_task.task_metadata["resume_from_stage"] == stage
    if stage == "linkage":
        assert retry_task.task_metadata["skip_duplicate_precheck"] is False
        assert retry_task.task_metadata["retry_linkage_required"] is True
    assert retry_task.task_metadata["work_name"] == "重命名失败作品"
    assert retry_task.task_metadata["rename_retry_classify_enabled"] is True
    assert retry_task.task_metadata["retry_failed_task_id"] == "failed-task-id"
    assert "failure_stage" not in retry_task.task_metadata
