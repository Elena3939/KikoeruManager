import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

import app.core.circle_external_search_service as external
from app.core.asmr_download_service import ASMRDownloadService
from app.core.circle_image_cache_service import CircleImageCacheService
from app.core.http_client_lifecycle import HttpClientLifecycle


class FakeClient:
    def __init__(self):
        self.is_closed = False

    async def aclose(self):
        self.is_closed = True


def test_retired_pool_waits_for_other_request():
    async def run():
        lifecycle = HttpClientLifecycle()
        client = FakeClient()
        discarded = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def healthy():
            async with lifecycle.use(client, discarded.append):
                entered.set()
                await release.wait()
                assert not client.is_closed

        task = asyncio.create_task(healthy())
        await entered.wait()
        with pytest.raises(httpx.ConnectTimeout):
            async with lifecycle.use(client, discarded.append):
                raise httpx.ConnectTimeout("模拟 TLS 超时")
        assert discarded == [client]
        assert not client.is_closed
        release.set()
        await task
        assert client.is_closed
        assert not lifecycle._active
        assert not lifecycle._retired

    asyncio.run(run())


def test_cancelled_request_retires_pool():
    async def run():
        lifecycle = HttpClientLifecycle()
        client = FakeClient()
        entered = asyncio.Event()
        discarded = []

        async def request():
            async with lifecycle.use(client, discarded.append):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(request())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert discarded == [client]
        assert client.is_closed

    asyncio.run(run())


def test_old_failed_cover_client_cannot_discard_replacement():
    service = CircleImageCacheService()
    old = FakeClient()
    replacement = FakeClient()
    service._client = replacement

    async def run():
        with pytest.raises(httpx.ConnectTimeout):
            async with service._client_lifecycle.use(old, service._discard_client):
                raise httpx.ConnectTimeout("旧连接失败")
        assert service._client is replacement
        assert not replacement.is_closed
        assert old.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.PoolTimeout])
def test_external_search_replaces_failed_pool(monkeypatch, error):
    clients = []

    class Client(FakeClient):
        def __init__(self, **kwargs):
            super().__init__()
            assert kwargs["trust_env"] is False
            clients.append(self)

        async def get(self, url, **kwargs):
            if len(clients) == 1:
                raise error("模拟异常池")
            return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(external.httpx, "AsyncClient", Client)

    async def run():
        service = external.CircleExternalSearchService()
        with pytest.raises(error):
            await service._fetch_text("https://example.test/")
        assert clients[0].is_closed
        assert not service._clients
        assert await service._fetch_text("https://example.test/") == "ok"
        await service.stop()
        assert clients[1].is_closed

    asyncio.run(run())


def test_connect_tunnel_tls_timeouts_never_exhaust_shared_pool(monkeypatch):
    original_client = httpx.AsyncClient
    clients = []

    def build(**kwargs):
        kwargs["timeout"] = httpx.Timeout(0.1)
        kwargs["limits"] = httpx.Limits(max_connections=1)
        kwargs["verify"] = False
        client = original_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(external.httpx, "AsyncClient", build)

    async def run():
        handlers = set()

        async def proxy(reader, writer):
            handlers.add(asyncio.current_task())
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                assert headers.startswith(b"CONNECT ")
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
                # 隧道建立后不回应 TLS，模拟生产代理链路卡在 start_tls。
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        service = external.CircleExternalSearchService()
        try:
            for _ in range(6):
                with pytest.raises(httpx.ConnectTimeout):
                    await service._fetch_text("https://example.test/", proxy=f"http://127.0.0.1:{port}")
                assert not service._clients
            assert len(clients) == 6
            assert all(client.is_closed for client in clients)
        finally:
            await service.stop()
            server.close()
            await server.wait_closed()
            await asyncio.wait_for(asyncio.gather(*handlers), timeout=2)

    asyncio.run(run())


def test_south_plus_expired_cookie_pauses_source_and_config_change_resumes(monkeypatch):
    config = SimpleNamespace(south_plus_enabled=True, south_plus_cookie="expired", south_plus_proxy="")
    monkeypatch.setattr(external, "get_config", lambda: SimpleNamespace(circle_external_search=config))
    service = external.CircleExternalSearchService()
    calls = []

    async def fetch(*args, **kwargs):
        calls.append(1)
        return "用户组权限：你所属的用户组不能使用搜索功能。您还不是论坛会员,请先登录论坛"

    monkeypatch.setattr(service, "_fetch_south_plus_text", fetch)

    async def run():
        first = await service._fetch_source("south_plus", "RJ01694635")
        assert first["error_code"] == "login_required"
        second = await service._fetch_source("south_plus", "RJ01694636")
        assert second["status"] == "unavailable"
        assert len(calls) == 1
        config.south_plus_cookie = "new-cookie"
        assert service._source_backoff("south_plus") is None
        tested = await service.test_south_plus_connection("expired")
        assert tested["status"] == "login_required"

    asyncio.run(run())


def test_old_request_cannot_pause_changed_config(monkeypatch):
    config = SimpleNamespace(south_plus_enabled=True, south_plus_cookie="old", south_plus_proxy="")
    monkeypatch.setattr(external, "get_config", lambda: SimpleNamespace(circle_external_search=config))
    service = external.CircleExternalSearchService()
    signature = service._source_signature("south_plus")
    config.south_plus_cookie = "new"
    service._pause_source("south_plus", "login_required", 600, signature)
    assert service._source_backoff("south_plus") is None


def test_south_plus_successful_test_clears_only_matching_config_backoff(monkeypatch):
    config = SimpleNamespace(south_plus_enabled=True, south_plus_cookie="current", south_plus_proxy="")
    monkeypatch.setattr(external, "get_config", lambda: SimpleNamespace(circle_external_search=config))
    service = external.CircleExternalSearchService()
    signature = service._source_signature("south_plus")
    service._pause_source("south_plus", "ConnectTimeout", 300, signature)

    async def fetch(*args, **kwargs):
        return "<html>没有匹配结果</html>"

    monkeypatch.setattr(service, "_fetch_south_plus_text", fetch)

    async def run():
        assert (await service.test_south_plus_connection("unsaved"))["success"]
        assert service._source_backoff("south_plus") == "ConnectTimeout"
        assert (await service.test_south_plus_connection("current"))["success"]
        assert service._source_backoff("south_plus") is None

    asyncio.run(run())


def test_login_link_alone_is_not_an_expired_cookie_page():
    assert external.CircleExternalSearchService._south_plus_access_error(
        '<a href="login.php">请先登录</a><a href="read.php?tid=1">RJ01694635</a>'
    ) == ""


def test_paused_source_snapshot_keeps_hits_and_exposes_reason(monkeypatch):
    config = SimpleNamespace(south_plus_enabled=True, south_plus_cookie="expired", south_plus_proxy="")
    monkeypatch.setattr(external, "get_config", lambda: SimpleNamespace(circle_external_search=config))
    service = external.CircleExternalSearchService()
    service._pause_source("south_plus", "login_required", 600, service._source_signature("south_plus"))

    def load(keys):
        return {
            (source, rjcode): {
                "status": "hit" if rjcode == "RJ01694635" else "pending",
                "results": [{"url": "https://example.test/known", "title": rjcode}] if rjcode == "RJ01694635" else [],
                "search_url": service._source_search_url(source, rjcode),
            }
            for source, rjcode in keys
        }

    monkeypatch.setattr(service, "_load_or_enqueue_records", load)
    result = asyncio.run(service.search_variants({
        code: [{"rjcode": code}] for code in ("RJ01694635", "RJ01694636")
    }))["items"]
    assert result["RJ01694635"]["south_plus"]["status"] == "hit"
    assert result["RJ01694636"]["south_plus"]["status"] == "unavailable"
    assert result["RJ01694636"]["south_plus"]["error_codes"] == ["login_required"]


def test_persistent_record_keeps_concrete_error_code(monkeypatch):
    service = external.CircleExternalSearchService()
    row = SimpleNamespace(
        id=1, source="south_plus", rjcode="RJ01694635", attempt_count=0, updated_at=None,
        search_url=service._south_plus_search_url("RJ01694635"),
    )

    class DB:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return row

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(external, "SessionLocal", DB)
    completed = service._complete_record("1", {"status": "unavailable", "error_code": "login_required"})
    assert completed["status"] == "unavailable"
    assert row.last_error_code == "login_required"
    assert row.lease_until is None
    assert row.attempt_count == 1
    assert service._record_payload(row)["error_code"] == "login_required"
    service._complete_record("1", {"status": "miss"})
    assert row.last_error_code == ""


def test_cover_tls_timeout_retires_client_and_returns_diagnostic(tmp_path, monkeypatch):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    client = FakeClient()

    class Stream:
        async def __aenter__(self):
            raise httpx.ConnectTimeout("模拟 TLS 超时")

        async def __aexit__(self, *args):
            pass

    def stream(*args, **kwargs):
        assert "trace" in kwargs["extensions"]
        return Stream()

    client.stream = stream

    async def get_client():
        service._client = client
        return client

    monkeypatch.setattr(service, "_get_client", get_client)

    async def run():
        assert await service.fetch_local_for_rjcode("RJ01694635", force=True) is None
        assert client.is_closed
        assert service._client is None
        assert "ConnectTimeout" in service.failure_detail("RJ01694635")["error_code"]
        assert not service.has_known_missing("RJ01694635")
        assert not list(tmp_path.glob("*.tmp"))

    asyncio.run(run())


def test_cover_total_timeout_tracks_tls_stage_and_retires_pool(tmp_path, monkeypatch):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    service.ON_DEMAND_TOTAL_TIMEOUT_SECONDS = 0.01
    client = FakeClient()

    class Stream:
        async def __aenter__(self):
            await self.trace("proxy.start_tls.started", {})
            await asyncio.Event().wait()

        async def __aexit__(self, *args):
            pass

    def stream(*args, **kwargs):
        result = Stream()
        result.trace = kwargs["extensions"]["trace"]
        return result

    client.stream = stream

    async def get_client():
        service._client = client
        return client

    monkeypatch.setattr(service, "_get_client", get_client)

    async def run():
        assert await service.fetch_local_for_rjcode("RJ01694635") is None
        detail = service.failure_detail("RJ01694635")
        assert detail["error_code"] == "total-timeout:tls-handshake:direct"
        assert "TLS" in detail["detail"]
        assert client.is_closed
        assert service._client is None

    asyncio.run(run())


def test_cover_forced_retry_does_not_keep_old_404_conclusion(tmp_path, monkeypatch):
    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    service._mark_known_missing("RJ01694635")

    async def fail(*args, **kwargs):
        return False, "ConnectTimeout:tls-handshake:proxy", True

    monkeypatch.setattr(service, "_download_with_outcome", fail)

    async def run():
        assert await service.fetch_local_for_rjcode("RJ01694635", force=True) is None
        assert not service.has_known_missing("RJ01694635")
        detail = service.failure_detail("RJ01694635")
        assert detail["error_code"] == "ConnectTimeout:tls-handshake:proxy"
        assert "元数据代理链路" in detail["detail"]

    asyncio.run(run())


def test_cover_failure_diagnostics_are_bounded():
    service = CircleImageCacheService()
    service.MAX_FAILURE_CACHE_ENTRIES = 2
    for number in range(3):
        service._set_failure_detail(f"RJ{number:08d}", "card", "total-timeout")
    assert len(service._failure_details) == 2


def test_asmr_open_circuit_does_not_extend_or_repeat_warning(caplog):
    service = ASMRDownloadService(config=SimpleNamespace(http_proxy=""))
    with caplog.at_level(logging.WARNING):
        for _ in range(service.CIRCUIT_FAILURE_THRESHOLD):
            service._record_asmr_api_failure("ConnectionTimeoutError")
        deadline = service._api_circuit_open_until
        service._record_asmr_api_failure("ConnectionTimeoutError")
        for _ in range(10):
            assert service._skip_asmr_api_when_circuit_open("请求", "RJ01694635")
    assert service._api_circuit_open_until == deadline
    assert len(caplog.records) == 1


def test_asmr_proxy_change_clears_old_circuit():
    config = SimpleNamespace(http_proxy="http://old-proxy:8080")
    service = ASMRDownloadService(config=config)
    for _ in range(service.CIRCUIT_FAILURE_THRESHOLD):
        service._record_asmr_api_failure("ConnectionTimeoutError")
    assert service._asmr_api_circuit_open()
    config.http_proxy = "http://new-proxy:8080"
    assert not service._asmr_api_circuit_open()
    assert service._api_failure_count == 0


def test_asmr_404_is_missing_not_network_failure(caplog):
    service = ASMRDownloadService(config=SimpleNamespace(http_proxy=""))

    class Response:
        status = 404

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        closed = False

        def get(self, *args, **kwargs):
            return Response()

    service._session = Session()
    with caplog.at_level(logging.WARNING):
        data, status = asyncio.run(service.fetch_work_info_with_status("RJ01694635"))
    assert data is None
    assert status == "missing"
    assert service._api_failure_count == 0
    assert not caplog.records


def test_cover_fetch_api_returns_concrete_failure(tmp_path, monkeypatch):
    from app.api.routes import CircleCompletionCoverFetchRequest, circle_completion_fetch_cover
    from app.core import circle_image_cache_service

    service = CircleImageCacheService()
    service._cache_dir = tmp_path
    service._set_failure_detail("RJ01694635", "card", "ConnectTimeout:tls-handshake:proxy")

    async def fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "fetch_local_for_rjcode", fetch)
    monkeypatch.setattr(circle_image_cache_service, "get_circle_image_cache_service", lambda: service)
    result = asyncio.run(circle_completion_fetch_cover(CircleCompletionCoverFetchRequest(rjcode="RJ01694635")))
    assert result["success"] is False
    assert result["error_code"] == "ConnectTimeout:tls-handshake:proxy"
    assert "TLS" in result["detail"]
