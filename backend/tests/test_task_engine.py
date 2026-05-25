"""
任务引擎测试
"""
import pytest
import asyncio
import os
import shutil
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import settings as settings_module
from app.core.task_engine import TaskEngine, Task, TaskType, TaskStatus
from app.models import database as database_module
from app.models.database import ConflictWork

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
    async def test_submit_task(self, engine, sample_task):
        """测试提交任务"""
        task_id = await engine.submit(sample_task)
        
        assert task_id is not None
        assert sample_task.id == task_id
        assert len(engine.tasks) == 1
        assert engine.tasks[task_id] == sample_task
    
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
