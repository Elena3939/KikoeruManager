"""内部清理竞争、封面缓存和邮件会话错误的回归。"""

import asyncio
import io
import shutil
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from app.core.circle_image_cache_service import CircleImageCacheService
from app.core.input_scan_service import InputScanService
from app.core import email_watcher_service as mail


def image_bytes(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="JPEG")
    return output.getvalue()


def test_cleanup_missing_child_completes_and_clears_record(tmp_path, monkeypatch):
    stage = tmp_path / ("scan_stage_" + "a" * 32)
    stage.mkdir()
    child = stage / "clone.part"
    child.write_bytes(b"data")
    repository = SimpleNamespace(
        stage_paths=lambda *args: [("owner", str(stage))], clear_stage=Mock(),
    )
    real_unlink = __import__("os").unlink

    def racing_unlink(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        raise FileNotFoundError(str(path))

    monkeypatch.setattr("os.unlink", racing_unlink)
    asyncio.run(InputScanService(repository)._cleanup_stages("scan"))
    assert not stage.exists()
    repository.clear_stage.assert_called_once_with("owner", str(stage))


def test_cleanup_missing_root_completes(tmp_path):
    stage = str(tmp_path / ("scan_stage_" + "b" * 32))
    repository = SimpleNamespace(
        stage_paths=lambda *args: [("owner", stage)], clear_stage=Mock(),
    )
    asyncio.run(InputScanService(repository)._cleanup_stages("scan"))
    repository.clear_stage.assert_called_once_with("owner", stage)


@pytest.mark.parametrize("remaining", [False, True])
def test_cleanup_failure_preserves_record(tmp_path, monkeypatch, remaining):
    stage = tmp_path / ("scan_stage_" + "c" * 32)
    stage.mkdir()
    repository = SimpleNamespace(
        stage_paths=lambda *args: [("owner", str(stage))], clear_stage=Mock(),
    )

    def fail(path, *, onerror):
        if not remaining:
            error = PermissionError("拒绝访问")
            onerror(None, path, (PermissionError, error, None))

    monkeypatch.setattr(shutil, "rmtree", fail)
    with pytest.raises(OSError):
        asyncio.run(InputScanService(repository)._cleanup_stages("scan"))
    repository.clear_stage.assert_not_called()


def test_cover_detects_corruption_and_replacement(tmp_path):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    target = service.get_local_path("RJ01694635")
    target.write_bytes(image_bytes())
    assert service.has_local("RJ01694635")
    target.write_bytes(b"<html>error</html>")
    assert not service.has_local("RJ01694635")
    target.write_bytes(image_bytes()[:-30])
    assert not service.has_local("RJ01694635")
    target.write_bytes(image_bytes("blue"))
    assert service.has_local("RJ01694635")


@pytest.mark.parametrize("force,old_valid", [(True, True), (False, False)])
def test_cover_refreshes_existing_file(tmp_path, monkeypatch, force, old_valid):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    target = service.get_local_path("RJ01694635")
    target.write_bytes(image_bytes() if old_valid else b"invalid")
    replacement = image_bytes("blue")
    calls = []

    async def download(*args, **kwargs):
        calls.append(args)
        target.write_bytes(replacement)
        return True, "", False

    monkeypatch.setattr(service, "_download_with_outcome", download)
    assert asyncio.run(service.fetch_local_for_rjcode("RJ01694635", force=force)) == target
    assert len(calls) == 1
    assert target.read_bytes() == replacement


def test_invalid_download_does_not_replace_good_cover(tmp_path, monkeypatch):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    original = image_bytes()
    target = service.get_local_path("RJ01694635")
    target.write_bytes(original)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"not an image")
        )) as client:
            async def get_client():
                return client
            monkeypatch.setattr(service, "_get_client", get_client)
            result = await service._download_once("RJ01694635", "https://example.test/cover.jpg")
            assert result == (False, "invalid-image", False)
    asyncio.run(run())
    assert target.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_download_one_force_replaces_existing_cover(tmp_path, monkeypatch):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    target = service.get_local_path("RJ01694635")
    target.write_bytes(image_bytes())
    replacement = image_bytes("blue")

    async def download(*args, **kwargs):
        target.write_bytes(replacement)
        return True, "", False

    monkeypatch.setattr(service, "_download_with_outcome", download)
    assert asyncio.run(service.download_one("RJ01694635", "https://example.test/cover.jpg", force=True))
    assert target.read_bytes() == replacement


def test_alias_restore_skips_corrupt_source_and_replaces_corrupt_target(tmp_path):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    target = service.get_local_path("RJ01694635")
    target.write_bytes(b"broken target")
    service.get_local_path("RJ01694636").write_bytes(b"broken alias")
    source = service.get_local_path("RJ01694637")
    source.write_bytes(image_bytes())
    assert service.restore_from_legacy_alias("RJ01694635", ["RJ01694636", "RJ01694637"]) == target
    assert target.read_bytes() == source.read_bytes()
    assert not list(tmp_path.glob("*.tmp"))


def test_idle_configuration_change_exits_cleanly(monkeypatch):
    service = mail.EmailWatcherService()
    service._fetch_and_process = Mock()
    client = Mock()
    client.idle_check.return_value = []
    config = SimpleNamespace(email_watcher=SimpleNamespace(
        imap_host="example.test", imap_port=993, imap_ssl=True,
        idle_timeout_minutes=25, proxy_url="", username="test", password="test", mailbox="INBOX",
    ))
    monkeypatch.setattr(mail, "create_imap_client", lambda **kwargs: nullcontext(client))
    monkeypatch.setattr("app.config.settings.get_config", lambda: SimpleNamespace(email_watcher=None))
    service._run_idle_session(config)
    client.idle_done.assert_called_once()
    service._fetch_and_process.assert_called_once_with(client, config)


@pytest.mark.parametrize("bye", [False, True])
def test_idle_read_failure_does_not_send_done(monkeypatch, bye):
    import imapclient

    service = mail.EmailWatcherService()
    service._fetch_and_process = Mock()
    client = Mock()
    if bye:
        client.idle_check.return_value = [(b"BYE", b"session closed")]
    else:
        client.idle_check.side_effect = ValueError("原始读取错误")
    client.idle_done.side_effect = BrokenPipeError("二次错误")
    config = SimpleNamespace(email_watcher=SimpleNamespace(
        imap_host="example.test", imap_port=993, imap_ssl=True,
        idle_timeout_minutes=25, proxy_url="", username="test", password="test", mailbox="INBOX",
    ))
    monkeypatch.setattr(mail, "create_imap_client", lambda **kwargs: nullcontext(client))
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    with pytest.raises(imapclient.IMAPClient.AbortError if bye else ValueError):
        service._run_idle_session(config)
    client.idle_done.assert_not_called()
