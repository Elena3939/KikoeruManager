"""列表封面跨社团、进程重建与历史缓存修复的回归。"""

import asyncio

import httpx
from PIL import Image

from app.core.circle_image_cache_service import CircleImageCacheService


def cache_service(directory):
    service = CircleImageCacheService()
    service._cache_dir = directory
    return service


def test_list_read_never_returns_card(tmp_path):
    service = cache_service(tmp_path)
    card = service.get_local_path("RJ01486845")
    Image.new("RGB", (640, 480), "red").save(card)
    assert service.resolve_filename("RJ01486845_sam.jpg") == service.get_local_path("RJ01486845", "list")
    assert service.resolve_filename("../RJ01486845_sam.jpg") is None


def test_list_restores_before_negative_cache_without_network(tmp_path, monkeypatch):
    service = cache_service(tmp_path)
    Image.new("RGB", (640, 480), "red").save(service.get_local_path("RJ01486845"))
    service._mark_known_missing("RJ01486845", "list")
    service._remember_failure("RJ01486845", "list")

    async def unexpected_network(*args, **kwargs):
        raise AssertionError("本地主图存在时不应访问网络")

    monkeypatch.setattr(service, "_download_with_outcome", unexpected_network)
    target = asyncio.run(service.ensure_local_for_filename("RJ01486845_sam.jpg"))
    assert target == service.get_local_path("RJ01486845", "list")
    with Image.open(target) as image:
        assert image.size == (240, 180)
    assert not service.has_known_missing("RJ01486845", "list")
    restarted = cache_service(tmp_path)
    assert restarted.resolve_filename("RJ01486845_sam.jpg") == target
    assert restarted.has_local("RJ01486845", "list")
    assert not list(tmp_path.glob("*.tmp"))


def test_restore_preserves_existing_valid_thumbnail_and_card(tmp_path):
    service = cache_service(tmp_path)
    card = service.get_local_path("RJ01486845")
    thumb = service.get_local_path("RJ01486845", "list")
    Image.new("RGB", (640, 480), "red").save(card)
    Image.new("RGB", (100, 100), "blue").save(thumb)
    originals = card.read_bytes(), thumb.read_bytes()
    assert service.restore_list_from_card("RJ01486845") == thumb
    assert (card.read_bytes(), thumb.read_bytes()) == originals


def test_background_restore_ignores_stale_missing_marker(tmp_path):
    service = cache_service(tmp_path)
    Image.new("RGB", (640, 480), "red").save(service.get_local_path("RJ01486845"))
    service._mark_known_missing("RJ01486845", "list")

    async def read():
        task = service.schedule_ensure_for_filename("RJ01486845_sam.jpg")
        assert task is not None
        await task

    asyncio.run(read())
    assert service.has_local("RJ01486845", "list")


def test_download_card_also_persists_list(tmp_path, monkeypatch):
    service = cache_service(tmp_path)
    source = tmp_path / "source.jpg"
    Image.new("RGB", (640, 480), "red").save(source)
    content = source.read_bytes()

    async def download():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=content)
        )) as client:
            async def get_client():
                return client
            monkeypatch.setattr(service, "_get_client", get_client)
            assert await service._download_once("RJ01486845", "https://example.test/cover.jpg") == (True, "", False)

    asyncio.run(download())
    restarted = cache_service(tmp_path)
    assert restarted.has_local("RJ01486845", "list")
    with Image.open(restarted.resolve_filename("RJ01486845_sam.jpg")) as image:
        assert image.size == (240, 180)
