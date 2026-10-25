"""稳定证据必须覆盖整组，短间隔轮询不能改变观察窗口。"""

from app.core.input_stability import observe_sources, valid_stability_evidence
from app.core.input_stability import check_task_sources
from types import SimpleNamespace
import pytest


def test_three_adjacent_observations_include_main_volume(tmp_path):
    paths = [str(tmp_path / name) for name in ("a.7z.001", "a.7z.002")]
    for path in paths:
        with open(path, "wb") as stream:
            stream.write(b"data")
    evidence = {}
    for instant in (100, 102, 104):
        evidence, reason = observe_sources(paths, evidence, checks=3, interval=2, now=instant)
        assert not evidence["verified"]
    evidence, reason = observe_sources(paths, evidence, checks=3, interval=2, now=106)
    assert reason is None
    assert valid_stability_evidence(evidence, paths, checks=3, interval=2, now=107)
    with open(paths[0], "ab") as stream:
        stream.write(b"changed")
    assert not valid_stability_evidence(evidence, paths, checks=3, interval=2, now=107)


def test_early_poll_does_not_restart_stable_window(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"data")
    evidence, _ = observe_sources([str(path)], {}, checks=1, interval=2, now=100)
    early, _ = observe_sources([str(path)], evidence, checks=1, interval=2, now=101)
    assert early == evidence
    verified, _ = observe_sources([str(path)], early, checks=1, interval=2, now=102)
    assert verified["verified"]
    assert not valid_stability_evidence(verified, [str(path)], checks=2, interval=2, now=103)
    assert not valid_stability_evidence(verified, [str(path)], checks=1, interval=2, now=120)
    (tmp_path / "a.zip.aria2").write_bytes(b"")
    assert not valid_stability_evidence(verified, [str(path)], checks=1, interval=2, now=103)


def test_manual_single_archive_only_samples_identity(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"data")
    evidence, reason = observe_sources(
        [str(path)], {}, checks=3, interval=2, needs_stability=False, now=100,
    )
    assert reason is None and evidence["verified"]
    # 手扫未观察完整窗口，不能免掉执行前的稳定检查。
    assert not valid_stability_evidence(evidence, [str(path)], checks=3, interval=2, now=101)


def test_execution_observes_once_and_resets_expired_evidence(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"data")
    task = SimpleNamespace(source_path=str(path), task_metadata={"input_members": [str(path)]})
    config = SimpleNamespace(processing=SimpleNamespace(file_stable_checks=2, file_stable_interval=2))
    assert check_task_sources(task, config, now=100) == "file_changing"
    assert task.task_metadata["input_source_wait"]["next_check_at"] == 102
    assert check_task_sources(task, config, now=102) == "file_changing"
    assert check_task_sources(task, config, now=104) is None
    assert "input_source_wait" not in task.task_metadata
    assert check_task_sources(task, config, now=130) == "file_changing"
    with pytest.raises(TimeoutError):
        check_task_sources(task, config, now=140, max_wait=10)


@pytest.mark.asyncio
async def test_complete_volume_set_consumes_shared_evidence_without_sleep(tmp_path, monkeypatch):
    from app.core.extract_service import ExtractService
    from app.core.task_engine import Task, TaskType
    from app.config.settings import get_config
    import time

    paths = [str(tmp_path / f"a.7z.{number:03}") for number in range(1, 11)]
    for path in paths:
        with open(path, "wb") as stream:
            stream.write(b"data")
    config = get_config()
    evidence, _ = observe_sources(
        paths, {}, checks=config.processing.file_stable_checks,
        interval=config.processing.file_stable_interval, now=time.time(),
    )
    evidence.update(verified=True, consistent_checks=config.processing.file_stable_checks)
    task = Task(TaskType.AUTO_PROCESS, paths[0], metadata={
        "scan_id": "scan", "input_members": paths, "input_stability": evidence,
    })
    service = ExtractService()

    async def no_sleep(*args):
        pytest.fail("有效整组证据不能再次等待")

    monkeypatch.setattr("app.core.extract_service.asyncio.sleep", no_sleep)
    assert await service._wait_for_complete_set(SimpleNamespace(volumes=paths), task)
