"""
任务引擎测试
"""
import pytest
import asyncio
import os
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta

from app.config import settings as settings_module
from app.core import task_engine as task_engine_module
from app.core.task_engine import TaskEngine, Task, TaskType, TaskStatus
from app.models import database as database_module
from app.models.database import ConflictWork, ProcessedArchive, Task as TaskRecord, TaskCenterItem


def test_get_task_engine_reserves_asmr_file_download_slots(monkeypatch):
    """任务引擎容量至少覆盖全局文件并发，后续 RJ 才能使用空余槽位。"""
    engine = Mock()
    monkeypatch.setattr(task_engine_module, "_task_engine", engine)
    monkeypatch.setattr(
        settings_module,
        "get_config",
        lambda: SimpleNamespace(
            processing=SimpleNamespace(max_workers=2),
            asmr_sync=SimpleNamespace(max_concurrent_downloads=5),
        ),
    )

    assert task_engine_module.get_task_engine() is engine
    engine.set_max_concurrent.assert_called_once_with(5)


class TestTaskEngine:
    """测试任务引擎"""
    
    @pytest.fixture
    def engine(self):
        """创建任务引擎实例"""
        return TaskEngine(max_concurrent=2)
    
    @pytest.fixture
    def sample_task(self):
        """创建示例任务"""
        return Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path="/test/file.zip",
            auto_classify=True
        )

    @pytest.mark.asyncio
    async def test_multi_rj_archive_precheck_marks_aggregate_before_business_prechecks(
        self,
        engine,
        tmp_path,
    ):
        source = tmp_path / "222(700241795).rar"
        source.write_bytes(b"rar")
        task = Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path=str(source),
            auto_classify=True,
            metadata={"rjcode": "RJ01606254"},
        )
        extract_service = SimpleNamespace(
            collect_top_level_rjcodes=AsyncMock(
                return_value=["RJ01583281", "RJ01606253", "RJ01606254"]
            )
        )

        result = await engine._collect_multi_rj_archive_precheck(task, extract_service)

        assert result == ["RJ01583281", "RJ01606253", "RJ01606254"]
        assert task.task_metadata["aggregate_archive"] is True
        assert task.task_metadata["aggregate_rj_count"] == 3
        assert task.task_metadata["aggregate_rjcodes"] == result
        extract_service.collect_top_level_rjcodes.assert_awaited_once_with(
            str(source),
            task=task,
        )

    @pytest.mark.asyncio
    async def test_multi_rj_archive_precheck_respects_authoritative_rj_lock(
        self,
        engine,
        tmp_path,
    ):
        source = tmp_path / "bound.rar"
        source.write_bytes(b"rar")
        task = Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path=str(source),
            auto_classify=True,
            metadata={"rjcode_lock": True},
        )
        extract_service = SimpleNamespace(collect_top_level_rjcodes=AsyncMock())

        result = await engine._collect_multi_rj_archive_precheck(task, extract_service)

        assert result == []
        extract_service.collect_top_level_rjcodes.assert_not_awaited()
        assert "aggregate_archive" not in task.task_metadata

    @pytest.mark.asyncio
    async def test_uncertain_dlsite_retry_exhaustion_moves_to_waiting_manual(
        self,
        engine,
        tmp_path,
        monkeypatch,
    ):
        source = tmp_path / "RJ01606254.7z"
        source.write_bytes(b"archive")
        task = Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path=str(source),
            auto_classify=True,
            rjcode="RJ01606254",
            status=TaskStatus.WAITING_RETRY,
            metadata={
                "retry_kind": "dlsite_linkage_uncertain",
                "retry_count": 4,
                "retry_reason": "DLsite 关联链结果不完整",
            },
        )
        engine.tasks[task.id] = task
        record_problem = Mock()
        remove_waiting = Mock()
        monkeypatch.setattr(
            settings_module,
            "get_config",
            lambda: SimpleNamespace(asmr_sync=SimpleNamespace(max_retry_count=3)),
        )
        monkeypatch.setattr(engine, "_record_problem_work_for_task_failure", record_problem)
        monkeypatch.setattr(engine, "_remove_waiting_retry_task", remove_waiting)

        await engine._check_retry_tasks()

        assert task.status == TaskStatus.WAITING_MANUAL
        assert task.task_metadata["retry_exhausted"] is True
        assert task.task_metadata["available_actions"] == ["RETRY", "SKIP"]
        assert task.current_step == "等待人工: DLsite 关联链仍不完整，已停止自动重试"
        record_problem.assert_called_once_with(task, "RJ01606254", "DLsite 关联链结果不完整")
        remove_waiting.assert_called_once_with("RJ01606254")

    def test_uncertain_dlsite_retry_uses_fixed_schedule_and_business_key(
        self,
        engine,
    ):
        expected_delays = [
            timedelta(minutes=15),
            timedelta(hours=1),
            timedelta(hours=6),
        ]
        for completed_count, expected_delay in enumerate(expected_delays):
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=f"/test/RJ0160625{completed_count}.7z",
                rjcode=f"RJ0160625{completed_count}",
                metadata={"retry_count": completed_count},
            )
            before = datetime.now()

            retry_after = engine._schedule_dlsite_linkage_retry(
                task,
                "DLsite 关联链结果不完整",
            )

            assert retry_after is not None
            assert expected_delay - timedelta(seconds=1) <= retry_after - before
            assert retry_after - before <= expected_delay + timedelta(seconds=1)
            assert task.task_metadata["retry_count"] == completed_count + 1
            assert task.task_metadata["business_key"] == (
                f"{task.rjcode}:dlsite_linkage"
            )
            history = task.task_metadata["dlsite_linkage_attempt_history"]
            assert history[-1]["attempt"] == completed_count + 1
            assert task.status == TaskStatus.WAITING_RETRY

    @pytest.mark.asyncio
    async def test_retry_scheduler_respects_retry_after(
        self,
        engine,
    ):
        future_task = Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path="/test/RJ01606254.7z",
            rjcode="RJ01606254",
            status=TaskStatus.WAITING_RETRY,
            metadata={
                "retry_kind": "dlsite_linkage_uncertain",
                "retry_count": 1,
                "retry_after": (datetime.now() + timedelta(minutes=15)).isoformat(),
            },
        )
        due_task = Task(
            task_type=TaskType.AUTO_PROCESS,
            source_path="/test/RJ01606255.7z",
            rjcode="RJ01606255",
            status=TaskStatus.WAITING_RETRY,
            metadata={
                "retry_kind": "dlsite_linkage_uncertain",
                "retry_count": 1,
                "retry_after": (datetime.now() - timedelta(seconds=1)).isoformat(),
            },
        )
        engine.tasks[future_task.id] = future_task
        engine.tasks[due_task.id] = due_task

        await engine._check_retry_tasks(allow_without_retry_after=False)

        assert future_task.status == TaskStatus.WAITING_RETRY
        assert due_task.status == TaskStatus.PENDING
        queued = await asyncio.wait_for(engine.queue.get(), timeout=1)
        assert queued.id == due_task.id
    
    @pytest.mark.asyncio
    async def test_submit_task(self, engine, sample_task):
        """测试提交任务"""
        task_id = await engine.submit(sample_task)
        
        assert task_id is not None
        assert sample_task.id == task_id
        assert len(engine.tasks) == 1
        assert engine.tasks[task_id] == sample_task

    @pytest.mark.asyncio
    async def test_submit_auto_process_file_does_not_start_background_precheck(self, engine, sample_task, tmp_path, monkeypatch):
        """提交阶段不再启动低优先级清单预热，避免抢占 inspect 单槽。"""
        source = tmp_path / "RJ00000001.zip"
        source.write_bytes(b"dummy")
        sample_task.source_path = str(source)
        calls = []

        def fake_start_background_precheck(extract_service, task, *, label=None):
            calls.append((task.id, label))
            return None

        monkeypatch.setattr(engine, "_start_background_archive_precheck", fake_start_background_precheck)

        await engine.submit(sample_task)

        assert calls == []

    @pytest.mark.asyncio
    async def test_background_precheck_reuses_existing_task(self, engine, sample_task, tmp_path):
        """同一任务已经有后台预热时，不重复启动第二个 7zz l。"""
        source = tmp_path / "RJ00000002.zip"
        source.write_bytes(b"dummy")
        sample_task.source_path = str(source)
        started = 0

        class FakeExtractService:
            async def precheck_archive(self, task):
                nonlocal started
                started += 1
                await asyncio.sleep(0)
                return None

        first = engine._start_background_archive_precheck(FakeExtractService(), sample_task, label="RJ00000002")
        second = engine._start_background_archive_precheck(FakeExtractService(), sample_task, label="RJ00000002")

        assert first is second
        await first
        assert started == 1
    
    @pytest.mark.asyncio
    async def test_get_task(self, engine, sample_task):
        """测试获取任务"""
        await engine.submit(sample_task)
        
        retrieved = engine.get_task(sample_task.id)
        assert retrieved == sample_task
    
    @pytest.mark.asyncio
    async def test_get_pending_tasks(self, engine):
        """测试获取待处理任务"""
        # 创建多个任务
        for i in range(3):
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=f"/test/file{i}.zip"
            )
            await engine.submit(task)
        
        pending = engine.get_pending_tasks()
        assert len(pending) == 3
    
    def test_task_start(self, sample_task):
        """测试任务开始"""
        sample_task.start()
        
        assert sample_task.status == TaskStatus.PROCESSING
        assert sample_task.started_at is not None
        assert sample_task.current_step == "处理中"
    
    def test_task_complete(self, sample_task):
        """测试任务完成"""
        sample_task.start()
        sample_task.complete()
        
        assert sample_task.status == TaskStatus.COMPLETED
        assert sample_task.completed_at is not None
        assert sample_task.progress == 100
    
    def test_task_fail(self, sample_task):
        """测试任务失败"""
        sample_task.start()
        sample_task.fail("测试错误")
        
        assert sample_task.status == TaskStatus.FAILED
        assert sample_task.error_message == "测试错误"
        assert sample_task.completed_at is not None
    
    def test_task_pause_resume(self, sample_task):
        """测试任务暂停和恢复"""
        sample_task.start()
        sample_task.pause()
        
        assert sample_task.status == TaskStatus.PAUSED
        
        sample_task.resume()
        assert sample_task.status == TaskStatus.PROCESSING
    
    @pytest.mark.asyncio
    async def test_pause_task_by_id(self, engine, sample_task):
        """测试通过ID暂停任务"""
        await engine.submit(sample_task)
        sample_task.start()
        
        engine.pause_task(sample_task.id)
        assert sample_task.status == TaskStatus.PAUSED
    
    @pytest.mark.asyncio
    async def test_cancel_task(self, engine, sample_task):
        """测试取消任务"""
        await engine.submit(sample_task)
        
        engine.cancel_task(sample_task.id)
        assert sample_task.is_cancelled() is True
    
    def test_task_update_progress(self, sample_task):
        """测试更新进度"""
        sample_task.update_progress(50, "测试中")
        
        assert sample_task.progress == 50
        assert sample_task.current_step == "测试中"

    def test_task_update_progress_throttles_duplicate_events(self, sample_task):
        """高频重复进度只更新当前状态，不重复刷 progress_log / 任务中心事件。"""
        events = []
        sample_task.set_event_hook(lambda task, reason: events.append((task.progress, reason)))

        sample_task.update_progress(50, "下载中")
        sample_task.update_progress(50, "下载中 1.2MB/s")

        assert sample_task.progress == 50
        assert sample_task.current_step == "下载中 1.2MB/s"
        assert len(sample_task.task_metadata["progress_log"]) == 1
        assert events == [(50, "progress")]

    def test_task_update_progress_keeps_same_percent_stage_change(self, sample_task):
        """同百分比的真实阶段切换不能被进度节流吞掉。"""
        events = []
        sample_task.set_event_hook(lambda task, reason: events.append((task.current_step, reason)))

        sample_task.update_progress(50, "下载中")
        sample_task.update_progress(50, "校验文件")

        messages = [item["message"] for item in sample_task.task_metadata["progress_log"]]
        assert messages == ["下载中", "校验文件"]
        assert events == [("下载中", "progress"), ("校验文件", "progress")]

    def test_task_update_progress_throttles_numeric_refresh_with_same_base_step(self, sample_task):
        """同阶段的速度/数量刷新仍然节流，降低 metadata 写入和 SSE 风暴。"""
        events = []
        sample_task.set_event_hook(lambda task, reason: events.append((task.current_step, reason)))

        sample_task.update_progress(50, "上传中 1.2MB/s")
        sample_task.update_progress(50, "上传中 1.8MB/s")

        messages = [item["message"] for item in sample_task.task_metadata["progress_log"]]
        assert messages == ["上传中 1.2MB/s"]
        assert sample_task.current_step == "上传中 1.8MB/s"
        assert events == [("上传中 1.2MB/s", "progress")]

    def test_task_update_progress_always_records_terminal_step(self, sample_task):
        """终态进度不能被节流吞掉。"""
        sample_task.update_progress(99, "下载中")
        sample_task.update_progress(100, "完成")

        messages = [item["message"] for item in sample_task.task_metadata["progress_log"]]
        assert messages[-1] == "完成"
        assert sample_task.progress == 100

    def test_compact_progress_log_for_persistence_keeps_key_steps(self):
        """落库压缩只压缩副本，并保留首尾与关键节点。"""
        logs = [
            {
                "message": f"下载中 {index}",
                "progress": index % 100,
                "level": "info",
            }
            for index in range(40)
        ]
        logs[20] = {"message": "等待人工确认", "progress": 50, "level": "warning"}
        logs[-1] = {"message": "完成", "progress": 100, "level": "success"}
        metadata = {"progress_log": logs, "download_files": [{"name": "a.zip"}]}

        compacted = Task.compact_progress_log_for_persistence(metadata, TaskStatus.COMPLETED)

        assert len(metadata["progress_log"]) == 40
        assert len(compacted["progress_log"]) <= 24
        messages = [item["message"] for item in compacted["progress_log"]]
        assert "下载中 0" in messages
        assert "等待人工确认" in messages
        assert messages[-1] == "完成"
        assert compacted["progress_log_compacted"]["original_count"] == 40
        assert compacted["download_files"] == [{"name": "a.zip"}]
    
    @pytest.mark.asyncio
    async def test_wait_if_paused(self, sample_task):
        """测试暂停等待"""
        sample_task.start()
        sample_task.pause()
        
        # 在后台恢复任务
        async def resume_later():
            await asyncio.sleep(0.1)
            sample_task.resume()
        
        asyncio.create_task(resume_later())
        
        # 应该在一段时间后恢复
        await asyncio.wait_for(sample_task.wait_if_paused(), timeout=1.0)
        
        assert sample_task.status == TaskStatus.PROCESSING
    
    def test_add_progress_callback(self, engine):
        """测试添加进度回调"""
        callback = Mock()
        engine.add_progress_callback(callback)
        
        assert callback in engine._progress_callbacks

    @pytest.mark.asyncio
    async def test_archive_source_file_records_total_size_for_exe_e_volumes(
        self,
        engine,
        tmp_path,
        db_session,
        monkeypatch,
    ):
        """归档 .exe + .eNN 分卷时，ProcessedArchive.file_size 记录整组总大小。"""
        source_dir = tmp_path / "input"
        processed_dir = tmp_path / "processed"
        source_dir.mkdir()
        processed_dir.mkdir()
        exe = source_dir / "RJ01629292.exe"
        e01 = source_dir / "RJ01629292.e01"
        e02 = source_dir / "RJ01629292.e02"
        exe.write_bytes(b"x" * 700)
        e01.write_bytes(b"y" * 701)
        e02.write_bytes(b"z" * 123)

        monkeypatch.setattr(
            settings_module,
            "get_config",
            lambda: SimpleNamespace(
                storage=SimpleNamespace(
                    input_path=str(source_dir),
                    processed_archives_path=str(processed_dir),
                    temp_path=str(tmp_path / "temp"),
                    library_path=str(tmp_path / "library"),
                    existing_folders_path=str(tmp_path / "existing"),
                )
            ),
        )

        def fake_get_db():
            yield db_session

        monkeypatch.setattr(database_module, "get_db", fake_get_db)
        monkeypatch.setattr(
            "app.core.task_center_event_service.broadcast_processed_archive_changed",
            lambda *_args, **_kwargs: None,
        )

        task = Task(task_type=TaskType.AUTO_PROCESS, source_path=str(exe), task_id="archive-size-task")

        await engine._archive_source_file(task)

        archive = db_session.query(ProcessedArchive).filter_by(filename="RJ01629292.exe").one()
        assert archive.file_size == 1524
        assert archive.volume_count == 3
        assert archive.current_path == str(processed_dir / "RJ01629292.exe")
        assert sorted(path.name for path in processed_dir.iterdir()) == [
            "RJ01629292.e01",
            "RJ01629292.e02",
            "RJ01629292.exe",
        ]
        assert not exe.exists()

    def test_extract_subtask_conflict_source_moves_to_stable_conflicts_dir(self, engine, tmp_path, monkeypatch):
        temp_root = tmp_path / "temp"
        library_root = tmp_path / "library"
        holder = temp_root / "RJ00000011_subtask_parent"
        source = holder / "RJ00000011"
        source.mkdir(parents=True)
        (source / "track.wav").write_bytes(b"data")
        library_root.mkdir()

        monkeypatch.setattr(
            settings_module,
            "get_config",
            lambda: SimpleNamespace(storage=SimpleNamespace(library_path=str(library_root))),
        )

        task = Task(
            task_type=TaskType.PROCESS_EXISTING_FOLDER,
            source_path=str(source),
            metadata={
                "is_extract_subtask": True,
                "extract_subtask_temp_holder": str(holder),
            },
        )

        classifier = SimpleNamespace(_move_with_rename=lambda src, dst: shutil.move(src, os.path.join(dst, os.path.basename(src))))

        stable_path = asyncio.run(engine._stabilize_extract_subtask_conflict_source(task, str(source), classifier))

        assert stable_path.startswith(str(library_root / "_conflicts"))
        assert os.path.exists(stable_path)
        assert not os.path.exists(source)
        assert task.source_path == stable_path
        assert task.output_path == stable_path

        task.status = TaskStatus.WAITING_MANUAL
        asyncio.run(engine._cleanup_failed_task(task))

        assert os.path.exists(stable_path)
        assert not os.path.exists(holder)

    def test_rewrite_active_conflict_new_path_for_extract_subtask(self, engine, db_session, monkeypatch):
        old_path = "/tmp/RJ00000011_subtask_parent/RJ00000011"
        new_path = "/library/_conflicts/RJ00000011"

        db_session.add(
            ConflictWork(
                id="conflict-1",
                task_id="task-1",
                rjcode="RJ00000011",
                conflict_type="DUPLICATE",
                existing_path="/library/RJ00000011",
                new_path=old_path,
                new_metadata={},
                status="PENDING",
            )
        )
        db_session.commit()

        def fake_get_db():
            yield db_session

        monkeypatch.setattr(database_module, "get_db", fake_get_db)

        updated = engine._rewrite_active_conflict_new_path("task-1", old_path, new_path)

        row = db_session.query(ConflictWork).filter(ConflictWork.id == "conflict-1").one()
        assert updated == 1
        assert row.new_path == new_path
        assert row.new_metadata["new_path_recovered_from"] == old_path

    def test_recover_stale_processing_tasks_marks_waiting_retry(self, engine, db_session, monkeypatch):
        """启动时把没有内存运行态的旧 processing 快照恢复为可重试。"""
        stale_time = datetime.now() - timedelta(hours=2)
        fresh_time = datetime.now()
        engine.stale_processing_seconds = 60
        stale_task_id = "stale-task"
        fresh_task_id = "fresh-task"

        db_session.add(TaskRecord(
            id=stale_task_id,
            type=TaskType.AUTO_PROCESS.value,
            status=TaskStatus.PROCESSING.value,
            source_path="/tmp/stale.zip",
            progress=38,
            current_step="预检中",
            started_at=stale_time,
            task_metadata={"existing": True},
        ))
        db_session.add(TaskRecord(
            id=fresh_task_id,
            type=TaskType.AUTO_PROCESS.value,
            status=TaskStatus.PROCESSING.value,
            source_path="/tmp/fresh.zip",
            progress=38,
            current_step="预检中",
            started_at=fresh_time,
            task_metadata={},
        ))
        db_session.add(TaskCenterItem(
            item_id="engine:stale-task",
            engine_task_id=stale_task_id,
            domain="extract",
            status=TaskStatus.PROCESSING.value,
            kind="auto_process",
            title="旧任务",
            payload_json={
                "engine_task_id": stale_task_id,
                "status": TaskStatus.PROCESSING.value,
                "details": {"metadata": {"foo": "bar"}},
            },
            updated_at=stale_time,
        ))
        db_session.commit()

        monkeypatch.setattr(database_module, "SessionLocal", lambda: db_session)

        recovered = engine.recover_stale_processing_tasks()
        db_session.flush()

        stale_row = db_session.query(TaskRecord).filter(TaskRecord.id == stale_task_id).one()
        fresh_row = db_session.query(TaskRecord).filter(TaskRecord.id == fresh_task_id).one()
        stale_item = db_session.query(TaskCenterItem).filter(TaskCenterItem.item_id == "engine:stale-task").one()

        assert recovered == 1
        assert stale_row.status == TaskStatus.WAITING_RETRY.value
        assert stale_row.current_step.startswith("等待重试")
        assert stale_row.task_metadata["stale_processing_recovered"] is True
        assert fresh_row.status == TaskStatus.PROCESSING.value
        assert stale_item.status == TaskStatus.WAITING_RETRY.value
        assert stale_item.payload_json["status"] == TaskStatus.WAITING_RETRY.value
        assert stale_item.payload_json["details"]["metadata"]["stale_processing_recovered"] is True

    def test_task_snapshot_version_skips_unchanged_running_task(self, engine, sample_task):
        """运行中任务同一快照版本重复持久化时可以跳过 SQLite 写入。"""
        sample_task.start()
        sample_task.update_progress(30, "下载中")
        version_key = engine._task_snapshot_version_key(sample_task)

        assert engine._should_persist_task_snapshot(sample_task, version_key) is True

        engine._persisted_task_snapshot_versions[sample_task.id] = version_key

        assert engine._should_persist_task_snapshot(sample_task, version_key) is False

    def test_task_snapshot_version_persists_after_in_place_metadata_change(self, engine, sample_task):
        """metadata 原地变化必须继续落库，业务链路不一定会调用 touch_metadata。"""
        sample_task.start()
        version_key = engine._task_snapshot_version_key(sample_task)
        engine._persisted_task_snapshot_versions[sample_task.id] = version_key

        sample_task.task_metadata["download_runtime"] = {"completed_files": 1}
        next_version_key = engine._task_snapshot_version_key(sample_task)

        assert next_version_key != version_key
        assert engine._should_persist_task_snapshot(sample_task, next_version_key) is True

    def test_task_snapshot_version_always_persists_terminal_task(self, engine, sample_task):
        """终态任务重复调用仍允许落库，保证完成/失败/取消快照不会被节流吞掉。"""
        sample_task.start()
        sample_task.complete()
        version_key = engine._task_snapshot_version_key(sample_task)
        engine._persisted_task_snapshot_versions[sample_task.id] = version_key

        assert engine._should_persist_task_snapshot(sample_task, version_key) is True
