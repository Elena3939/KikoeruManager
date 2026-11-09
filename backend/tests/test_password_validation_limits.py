"""缺卷不能进入密码轮查，整包验证不能阻塞轻量清单。"""
import asyncio
import contextlib
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import extract_service as module
from app.core.extract_runtime import AdjustableLimiter
from app.core.extract_service import ArchiveInfo, ArchiveMissingVolumeError, ExtractService
from app.core.failure_reason_formatter import format_extract_failure_message
from app.core.task_engine import Task, TaskType


def make_task(tmp_path, name="RJ01737031.part01.rar"):
    path = tmp_path / name
    signature = b"PK\x03\x04" if name.endswith(".zip") else b"Rar!\x1a\x07\x01\x00"
    path.write_bytes(signature + b"x" * 100)
    return Task(task_type=TaskType.EXTRACT, source_path=str(path))


def test_part_group_excludes_independent_7z_and_keeps_rar_sfx(tmp_path):
    service = ExtractService()
    for name in ("RJ01737031.part01.rar", "RJ01737031.part02.rar",
                 "RJ01737031.part03.7z", "RJ01737031.part04.rar"):
        (tmp_path / name).write_bytes(b"archive")
    group = service._detect_volume_set(str(tmp_path / "RJ01737031.part01.rar"))
    assert [module.Path(path).name for path in group.volumes] == [
        "RJ01737031.part01.rar", "RJ01737031.part02.rar", "RJ01737031.part04.rar",
    ]
    assert service._detect_volume_set(str(tmp_path / "RJ01737031.part03.7z")) is None
    (tmp_path / "sfx.part1.exe").write_bytes(b"MZ")
    (tmp_path / "sfx.part2.rar").write_bytes(b"Rar!")
    assert len(service._detect_volume_set(str(tmp_path / "sfx.part1.exe")).volumes) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_listing_missing_volume_stops_before_other_passwords(tmp_path, monkeypatch, stream):
    service = ExtractService()
    task = make_task(tmp_path)
    output = {"stdout": b"", "stderr": b""}
    output[stream] = b"ERROR = Missing volume : RJ01737031.part07.rar"
    run = AsyncMock(return_value=subprocess.CompletedProcess([], 2, **output))
    negative = Mock()
    monkeypatch.setattr(service, "_run_7z_command", run)
    monkeypatch.setattr(service, "_remember_negative_password", negative)
    with pytest.raises(ArchiveMissingVolumeError, match="part07.rar"):
        await service._get_archive_info(
            task.source_path, password_candidates=[
                {"password": "first"}, {"password": "second"},
            ], task=task,
        )
    run.assert_awaited_once()
    negative.assert_not_called()


@pytest.mark.asyncio
async def test_missing_volume_reaches_task_failure_and_preserves_source(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path)
    monkeypatch.setattr(service, "_extract", AsyncMock(
        side_effect=ArchiveMissingVolumeError("ERROR = Missing volume : RJ01737031.part07.rar"),
    ))
    monkeypatch.setattr(service, "_cleanup_extract_runtime_state", AsyncMock())
    assert await service.extract(task) is None
    assert task.task_metadata["extract_failure_reason"] == "volume_incomplete"
    assert "part07.rar" in task.error_message
    assert module.Path(task.source_path).is_file()


@pytest.mark.asyncio
async def test_rar_without_listing_checks_structure_before_full_test(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path)
    run = AsyncMock(return_value=subprocess.CompletedProcess(
        [], 2, b"ERROR = Missing volume : RJ01737031.part07.rar", b"",
    ))
    full = AsyncMock()
    monkeypatch.setattr(service, "_run_7z_command", run)
    monkeypatch.setattr(service, "_probe_by_full_test", full)
    result = await service._try_extract(
        ArchiveInfo(task.source_path, []), str(tmp_path / "output"), task,
        password_candidates=[{"password": "first"}, {"password": "second"}],
    )
    assert result == (False, None, "volume_incomplete")
    run.assert_awaited_once()
    full.assert_not_awaited()


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", gate=None):
        self.returncode = None
        self.stdout_bytes = stdout
        self.stderr_bytes = stderr
        self.gate = gate
        self.started = asyncio.Event()

    async def communicate(self):
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        self.returncode = 2 if self.stdout_bytes or self.stderr_bytes else 0
        return self.stdout_bytes, self.stderr_bytes

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


def isolate_resources(service, monkeypatch):
    heavy, inspect = AdjustableLimiter(1), AdjustableLimiter(1)

    @contextlib.asynccontextmanager
    async def budget(*args, **kwargs):
        yield

    monkeypatch.setattr(module, "get_resource_budget_service", lambda: SimpleNamespace(
        snapshot=lambda: {}, acquire=budget,
    ))
    monkeypatch.setattr(service, "_get_7z_semaphore", lambda: heavy)
    monkeypatch.setattr(service, "_get_7z_inspect_semaphore", lambda: inspect)
    return heavy, inspect


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_full_test_missing_volume_overrides_password_hint_and_stops_loop(tmp_path, monkeypatch, stream):
    service = ExtractService()
    task = make_task(tmp_path, "archive.zip")
    isolate_resources(service, monkeypatch)
    output = {stream: b"Missing volume : next.rar\nWrong password?"}
    process = FakeProcess(**output)
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(service, "_probe_password", AsyncMock(return_value="unknown"))
    ready, results = await service._prepare_password_attempts(
        task.source_path, ["first", "second", "third"], [], task=task,
    )
    assert ready == []
    assert results["first"] == "missing_volume"
    assert task.task_metadata["password_probe_failure_reason"] == "volume_incomplete"
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_running_full_test_leaves_inspect_slot_free_and_cancellation_releases_resources(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path, "archive.zip")
    heavy, inspect = isolate_resources(service, monkeypatch)
    process = FakeProcess(gate=asyncio.Event())
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    pending = asyncio.create_task(service._probe_by_full_test(task.source_path, "secret", 60, task))
    try:
        await asyncio.wait_for(process.started.wait(), timeout=1)
        assert heavy.active == 1
        async with service._acquire_probe_inspect_slot(
            "test.fast_probe", task.source_path, wait_timeout=0.1,
        ) as acquired:
            assert acquired
            assert inspect.active == 1
            assert process.returncode is None
    finally:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert heavy.active == inspect.active == 0
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_timeout_retries_are_bounded_and_never_become_wrong_password(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path, "archive.zip")
    monkeypatch.setattr(service, "_probe_password", AsyncMock(return_value="unknown"))
    full = AsyncMock(return_value="timeout")
    monkeypatch.setattr(service, "_probe_by_full_test", full)
    ready, _ = await service._prepare_password_attempts(task.source_path, ["first"], [], task=task)
    assert ready == []
    assert [call.kwargs["timeout"] for call in full.await_args_list] == [60, 120]
    assert task.task_metadata["password_probe_failure_reason"] == "password_probe_inconclusive"
    assert task.task_metadata["password_candidate_unresolved"] == 1
    message = format_extract_failure_message({
        "extract_failure_reason": task.task_metadata["password_probe_failure_reason"],
    })
    assert "尚不能确定密码是否正确" in message


@pytest.mark.asyncio
async def test_total_budget_stops_remaining_candidates_without_wrong_password(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path, "archive.zip")
    clock = [0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(service, "PASSWORD_VALIDATION_TIMEOUT", 5)
    monkeypatch.setattr(service, "_probe_password", AsyncMock(return_value="unknown"))

    async def full(*args, **kwargs):
        assert kwargs["timeout"] == service.PROBE_FULL_TEST_TIMEOUT
        clock[0] += 6
        return "wrong_password"

    probe = AsyncMock(side_effect=full)
    monkeypatch.setattr(service, "_probe_by_full_test", probe)
    ready, _ = await service._prepare_password_attempts(
        task.source_path, ["first", "second", "third"], [], task=task,
    )
    assert ready == []
    probe.assert_awaited_once()
    assert probe.await_args.kwargs["timeout"] == service.PROBE_FULL_TEST_TIMEOUT
    assert task.task_metadata["password_candidate_unresolved"] == 2
    assert task.task_metadata["password_probe_failure_reason"] == "password_probe_inconclusive"


@pytest.mark.asyncio
async def test_resource_wait_does_not_consume_password_validation_budget(tmp_path, monkeypatch):
    service = ExtractService()
    task = make_task(tmp_path, "archive.zip")
    heavy, inspect = isolate_resources(service, monkeypatch)
    monkeypatch.setattr(service, "PASSWORD_VALIDATION_TIMEOUT", 0.1)
    monkeypatch.setattr(service, "_probe_password", AsyncMock(return_value="unknown"))
    process = FakeProcess(stderr=b"Wrong password")
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", create)
    await heavy.acquire()
    pending = asyncio.create_task(service._prepare_password_attempts(
        task.source_path, ["first"], [], task=task,
    ))
    try:
        await asyncio.sleep(0.05)
        create.assert_not_awaited()
        heavy.release()
        ready, _ = await asyncio.wait_for(pending, timeout=2)
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        if heavy.active:
            heavy.release()
    assert ready == []
    create.assert_awaited_once()
    assert process.returncode == 2
    assert task.task_metadata["password_probe_failure_reason"] == "wrong_password"


@pytest.mark.asyncio
@pytest.mark.parametrize("password,expected", [
    ("correct-secret", "ok"), ("incorrect-secret", "wrong_password"),
])
async def test_real_aes_zip_full_validation(tmp_path, monkeypatch, password, expected):
    service = ExtractService()
    executable = shutil.which(service.seven_zip)
    if not executable:
        pytest.skip("需要实际安装 7z")
    source = tmp_path / "payload.bin"
    source.write_bytes(b"password-validation-content" * 1024)
    archive = tmp_path / "encrypted.zip"
    subprocess.run(
        [executable, "a", "-tzip", "-mem=AES256", "-pcorrect-secret",
         str(archive), str(source)],
        check=True, capture_output=True, timeout=15,
    )
    heavy, inspect = isolate_resources(service, monkeypatch)
    assert await service._probe_by_full_test(
        str(archive), password, timeout=5, seven_zip_executable=executable,
    ) == expected
    assert heavy.active == inspect.active == 0
    assert set(path.name for path in tmp_path.iterdir()) == {"payload.bin", "encrypted.zip"}
