from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.dlsite_service import DLsiteApiService


class _DummyClient:
    created: list["_DummyClient"] = []

    def __init__(self, *, proxy=None, proxies=None, **kwargs) -> None:
        self.proxy = proxy
        self.proxies = proxies
        self.kwargs = kwargs
        self.is_closed = False
        self.__class__.created.append(self)

    async def aclose(self) -> None:
        self.is_closed = True


@pytest.mark.asyncio
async def test_dlsite_client_rebuilds_when_metadata_proxy_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DLsiteApiService()
    _DummyClient.created = []

    config = SimpleNamespace(metadata=SimpleNamespace(http_proxy="127.0.0.1:7890"))
    monkeypatch.setattr("app.config.settings.get_config", lambda: config)
    monkeypatch.setattr("app.core.dlsite_service.httpx.AsyncClient", _DummyClient)

    client = await service._get_client()
    assert client is _DummyClient.created[-1]
    assert service._client_proxy_url == "http://127.0.0.1:7890"
    assert client.proxy == "http://127.0.0.1:7890"

    config.metadata.http_proxy = "127.0.0.1:7897"
    client = await service._get_client()
    assert client is _DummyClient.created[-1]
    assert len(_DummyClient.created) == 2
    assert _DummyClient.created[0].is_closed is True
    assert service._client_proxy_url == "http://127.0.0.1:7897"
    assert client.proxy == "http://127.0.0.1:7897"
