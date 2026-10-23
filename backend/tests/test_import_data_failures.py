"""查询失败必须阻断写入，问题作品重试不得改变原操作语义。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.import_validation import ImportDataError, require_complete_linkage, require_import_metadata
from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


@pytest.mark.parametrize("metadata", [
    {},
    {"rjcode": "RJ01000001", "work_name": "RJ01000001", "metadata_source": "minimal"},
    {"rjcode": "RJ01000001", "work_name": "未经证实的标题"},
    {"rjcode": "RJ01000001", "work_name": "", "metadata_evidence_source": "dlsite_product"},
])
def test_unusable_metadata_blocks_import(metadata):
    with pytest.raises(ImportDataError) as error:
        require_import_metadata(metadata)
    assert error.value.stage == "metadata"


@pytest.mark.parametrize("status", [None, "unverified", "failed", "verified"])
def test_linkage_requires_verified_evidence(status):
    works = {"RJ01000001": SimpleNamespace(evidence_status=status)}
    if status == "verified":
        require_complete_linkage(works)
    else:
        with pytest.raises(ImportDataError, match="关联数据"):
            require_complete_linkage(works)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, [], RuntimeError("查询失败")])
async def test_full_linkage_failure_cannot_return_partial_verified_graph(monkeypatch, response):
    from app.core.dlsite_service import DLsiteApiService

    service = DLsiteApiService()
    service.get_translation_info = AsyncMock(return_value=SimpleNamespace(is_original=True))
    service.get_linked_works = AsyncMock(return_value={"RJ01000001": SimpleNamespace(evidence_status="verified")})
    service._fetch_api = AsyncMock(**({"side_effect": response} if isinstance(response, Exception) else {"return_value": response}))
    with pytest.raises(ImportDataError) as error:
        await service.get_full_linkage("RJ01000001", require_verified=True)
    assert error.value.stage == "linkage"
    assert not service.cache


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "metadata_failed", "rename_failed", "no_change"])
@pytest.mark.parametrize("library_type", ["local", "synology_filestation"])
async def test_api_rename_retry_only_renames_in_original_library(monkeypatch, outcome, library_type):
    from app.core.api_rename_failure_service import retry_api_rename

    library = SimpleNamespace(id="library-a", type=library_type)
    manager = SimpleNamespace(get_library_definition=Mock(return_value=library), rename=AsyncMock(return_value={"new_path": "/library/新名称"}))
    metadata = {"rjcode": "RJ01000001", "work_name": "作品", "maker_name": "社团", "metadata_evidence_source": "dlsite_product"}
    if outcome == "metadata_failed":
        metadata["metadata_source"] = "minimal"
    fetch = AsyncMock(return_value=metadata)
    rename = SimpleNamespace(
        config=SimpleNamespace(rename=SimpleNamespace(use_japanese_metadata=False)),
        _compile_name=Mock(return_value="RJ01000001" if outcome == "no_change" else "新名称"),
        _sanitize_filename=lambda value: value,
    )
    if outcome == "rename_failed":
        manager.rename.side_effect = OSError("目录被占用")
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: manager)
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr("app.core.rename_service.RenameService", lambda: rename)
    task = Task(task_type=TaskType.RENAME, source_path="/library/RJ01000001", rjcode="RJ01000001", metadata={"library_id": library.id, "source_operation": "api_rename"})

    if outcome in {"metadata_failed", "rename_failed"}:
        with pytest.raises((ImportDataError, OSError)):
            await retry_api_rename(task)
    else:
        result = await retry_api_rename(task)
        assert result == (task.source_path if outcome == "no_change" else "/library/新名称")
    fetch.assert_awaited_once_with(task.source_path, task, force_refresh=True)
    if outcome in {"metadata_failed", "no_change"}:
        manager.rename.assert_not_awaited()
    else:
        manager.rename.assert_awaited_once_with(library.id, task.source_path, "新名称", sync_index_mutation=True)


def test_failed_retry_updates_original_problem_with_latest_metadata(monkeypatch, tmp_path):
    from app.models import database

    conflict = SimpleNamespace(id="problem", rjcode="RJ01000001", status="PROCESSING", new_path=str(tmp_path), new_metadata={"metadata_source": "minimal", "source_task_type": "auto_process"})
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conflict
    monkeypatch.setattr(database, "get_db", lambda: iter([db]))
    monkeypatch.setattr("app.core.activity_log_service.log_conflict_resolution_activity", Mock())
    task = Task(task_type=TaskType.PROCESS_EXISTING_FOLDER, source_path=str(tmp_path), metadata={
        "conflict_resolution_conflict_id": "problem", "conflict_resolution_action": "RETRY",
        "metadata_source": "dlsite_product", "work_name": "新获取的可信标题",
        "failure_stage": "rename", "rename_retry_source_path": str(tmp_path),
    })
    task.fail("目录被占用")
    TaskEngine(max_concurrent=1)._finalize_conflict_resolution_task(task)
    assert conflict.status == "PENDING"
    assert conflict.new_metadata["metadata_source"] == "dlsite_product"
    assert conflict.new_metadata["work_name"] == "新获取的可信标题"
    assert conflict.new_metadata["failure_stage"] == "rename"
    assert conflict.new_metadata["error_message"] == "目录被占用"
    db.add.assert_not_called()
    db.delete.assert_not_called()


@pytest.mark.parametrize("library_type", ["local", "synology_filestation"])
def test_api_rename_failure_records_library_scoped_retry(monkeypatch, library_type):
    from app.core.api_rename_failure_service import record_api_rename_failure

    library = SimpleNamespace(id="library-a", type=library_type)
    manager = Mock()
    manager.get_library_definition.return_value = library
    classifier = Mock()
    monkeypatch.setattr("app.core.library_manager.get_library_manager", lambda: manager)
    monkeypatch.setattr("app.core.classifier.SmartClassifier", lambda: classifier)
    record_api_rename_failure(library.id, "/library/RJ01000001", "RJ01000001", "查询失败", stage="metadata")
    args = classifier._add_to_conflict_works.call_args.args
    assert args[2] == "PROCESS_FAILED"
    assert args[4] == "/library/RJ01000001"
    assert args[5]["source_operation"] == "api_rename"
    assert args[5]["library_id"] == library.id
    assert args[5]["failure_stage"] == "metadata"
    assert args[5]["source_task_type"] == TaskType.RENAME.value
    boundary_check = manager._assert_local_path_in_library if library_type == "local" else manager._resolve_remote_operation_path
    boundary_check.assert_called_once()


@pytest.mark.parametrize("library_id", ["library-a", "library-b"])
@pytest.mark.parametrize("status", ["PENDING", "PROCESSING"])
def test_api_rename_repeated_failure_refreshes_existing_problem(monkeypatch, library_id, status):
    from app.core.classifier import SmartClassifier

    existing = SimpleNamespace(status=status, new_metadata={"error_message": "旧错误", "resolution_task_id": "原重试任务"})
    db = Mock()
    db.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = existing
    monkeypatch.setattr("app.core.classifier.get_db", lambda: iter([db]))
    notify = Mock()
    monkeypatch.setattr("app.core.api_rename_failure_service.notify_api_rename_problem_changed", notify)
    metadata = {"source_operation": "api_rename", "library_id": library_id, "error_message": "新错误"}
    SmartClassifier()._add_to_conflict_works(None, "RJ01000001", "PROCESS_FAILED", "", "/library/RJ01000001", metadata)
    assert existing.new_metadata.items() >= metadata.items()
    assert existing.new_metadata["resolution_task_id"] == "原重试任务"
    assert existing.new_metadata["last_failed_at"]
    assert existing.status == status
    db.commit.assert_called_once()
    db.add.assert_not_called()
    notify.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {"product": {}, "metadata_verification_status": "unverified"}, RuntimeError("请求超时")])
async def test_original_maker_query_failure_cannot_use_translator_as_maker(monkeypatch, response):
    from app.core.metadata_service import MetadataService

    service = MetadataService()
    fetch = AsyncMock(**({"side_effect": response} if isinstance(response, Exception) else {"return_value": response}))
    monkeypatch.setattr(service, "_get_product_info_for_metadata", fetch)
    with pytest.raises(ImportDataError, match="原作"):
        await service._resolve_original_maker_fields({
            "maker_name": "翻译社团",
            "translation_info": {"is_original": False, "original_workno": "RJ01000001"},
        }, "RJ01000002")


@pytest.mark.asyncio
async def test_auto_import_metadata_failure_keeps_archive_and_extraction(monkeypatch, tmp_path):
    from app.config import settings

    source = tmp_path / "RJ01000001.zip"
    source.write_bytes(b"archive")
    extracted = tmp_path / "temp" / "RJ01000001"
    extracted.mkdir(parents=True)
    (extracted / "track.wav").write_bytes(b"audio")
    config = SimpleNamespace(
        auto_process=SimpleNamespace(extract=True, fetch_metadata=True, rename=True, filter=True, classify=True, archive=True, check_duplicate=True),
        storage=SimpleNamespace(temp_path=str(tmp_path / "temp")),
    )
    monkeypatch.setattr(settings, "get_config", lambda: config)
    monkeypatch.setattr("app.core.extract_service.ExtractService", lambda: SimpleNamespace(extract=AsyncMock(return_value=str(extracted))))
    monkeypatch.setattr("app.core.metadata_service.MetadataService", lambda: SimpleNamespace(fetch=AsyncMock(return_value={"rjcode": "RJ01000001", "metadata_source": "minimal"})))
    rename = Mock()
    classify = Mock()
    monkeypatch.setattr("app.core.rename_service.RenameService", rename)
    monkeypatch.setattr("app.core.classifier.SmartClassifier", classify)
    engine = TaskEngine(max_concurrent=1)
    monkeypatch.setattr(engine, "_should_skip_conflict_retry_precheck", lambda _task: True)
    monkeypatch.setattr(engine, "_notify_progress", AsyncMock())
    monkeypatch.setattr(engine, "persist_task_center_item_snapshot", Mock())
    monkeypatch.setattr(engine, "_record_problem_work_for_task_failure", Mock())
    monkeypatch.setattr(engine, "_archive_source_file", AsyncMock())
    monkeypatch.setattr("app.core.activity_log_service.log_task_lifecycle_event", Mock())
    monkeypatch.setattr("app.core.task_notification_service.enqueue_notification_check", AsyncMock())
    task = Task(task_type=TaskType.AUTO_PROCESS, source_path=str(source), rjcode="RJ01000001", metadata={"rjcode_lock": True, "temp_extract_path": str(extracted.parent)})
    await engine._process_task(task)
    assert task.status == TaskStatus.FAILED
    assert task.task_metadata["failure_stage"] == "metadata"
    assert task.task_metadata["rename_retry_archive_source_path"] == str(source)
    assert task.output_path == str(extracted)
    assert source.read_bytes() == b"archive"
    assert (extracted / "track.wav").read_bytes() == b"audio"
    rename.assert_not_called()
    classify.return_value.classify_and_move.assert_not_called()
    engine._archive_source_file.assert_not_awaited()
    engine._record_problem_work_for_task_failure.assert_called_once()
