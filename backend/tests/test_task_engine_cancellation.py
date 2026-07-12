import pytest

from app.core.task_engine import Task, TaskEngine, TaskStatus, TaskType


def _task() -> Task:
    return Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path="/test/cancelled-task.zip",
        auto_classify=True,
    )


def test_cancelled_task_cannot_be_overwritten_by_complete_or_fail():
    """worker 晚到的完成/失败回调不能覆盖用户取消终态。"""
    task = _task()
    task.start()
    task.cancel()
    cancelled_at = task.completed_at

    task.complete()
    task.fail("晚到错误")

    assert task.status == TaskStatus.CANCELLED
    assert task.completed_at == cancelled_at
    assert task.error_message is None


def test_remove_task_rejects_cancelled_task_still_in_processing_set():
    """取消只改变终态；worker 退出 processing 集合前仍不能清理任务。"""
    engine = TaskEngine(max_concurrent=1)
    task = _task()
    task.start()
    task.cancel()
    engine.tasks[task.id] = task
    engine.processing.add(task.id)

    with pytest.raises(RuntimeError, match="任务仍在执行中"):
        engine.remove_task(task.id)

    assert engine.get_task(task.id) is task
