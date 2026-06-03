import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.api import routes
from app.core.google_drive_oauth import (
    DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID,
    DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET,
)


def _patch_google_drive_config(monkeypatch, **values):
    defaults = {
        "google_drive_oauth_client_mode": "builtin",
        "google_drive_client_id": "",
        "google_drive_client_secret": "",
        "google_drive_refresh_token": "",
    }
    defaults.update(values)
    config = SimpleNamespace(
        http_downloader=SimpleNamespace(**defaults),
        metadata=SimpleNamespace(http_proxy=""),
    )
    monkeypatch.setattr(routes, "get_config", lambda: config)
    monkeypatch.setattr(
        routes,
        "get_security_gate_service",
        lambda: SimpleNamespace(
            is_enforced=lambda: False,
            get_client_ip=lambda _request: "127.0.0.1",
            get_active_blacklist=lambda _ip: None,
            verify_cookie=lambda _token: True,
        ),
    )
    return config


def test_google_drive_oauth_begin_uses_builtin_client(client: TestClient, monkeypatch):
    routes._google_drive_oauth_states.clear()
    _patch_google_drive_config(monkeypatch)
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", "builtin-client.apps.googleusercontent.com")
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_SECRET", raising=False)

    response = client.post("/api/http-download/google-drive/oauth-begin", json={
        "opener_origin": "http://localhost:5556",
    })

    assert response.status_code == 200
    data = response.json()
    parsed = urlparse(data["auth_url"])
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query["client_id"] == ["builtin-client.apps.googleusercontent.com"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["https://www.googleapis.com/auth/drive.readonly"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    state = query["state"][0]
    assert state in routes._google_drive_oauth_states
    assert routes._google_drive_oauth_states[state]["client_source"] == "builtin"
    assert routes._google_drive_oauth_states[state]["code_verifier"]
    assert data["client_source"] == "builtin"
    assert data["client_mode"] == "builtin"
    routes._google_drive_oauth_states.clear()


def test_google_drive_oauth_begin_uses_default_builtin_client_without_env(client: TestClient, monkeypatch):
    routes._google_drive_oauth_states.clear()
    _patch_google_drive_config(monkeypatch)
    for key in (
        "KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID",
        "KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_DRIVE_OAUTH_CLIENT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    response = client.post("/api/http-download/google-drive/oauth-begin", json={
        "opener_origin": "http://localhost:5556",
    })

    assert response.status_code == 200
    data = response.json()
    query = parse_qs(urlparse(data["auth_url"]).query)

    assert query["client_id"] == [DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID]
    assert data["client_source"] == "builtin"
    assert data["client_mode"] == "builtin"
    state = query["state"][0]
    assert routes._google_drive_oauth_states[state]["client_secret"] == DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET
    routes._google_drive_oauth_states.clear()


def test_google_drive_oauth_begin_custom_client_overrides_builtin(client: TestClient, monkeypatch):
    routes._google_drive_oauth_states.clear()
    _patch_google_drive_config(monkeypatch)
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", "builtin-client.apps.googleusercontent.com")

    response = client.post("/api/http-download/google-drive/oauth-begin", json={
        "client_mode": "custom",
        "client_id": "custom-client.apps.googleusercontent.com",
        "opener_origin": "http://localhost:5556",
    })

    assert response.status_code == 200
    data = response.json()
    query = parse_qs(urlparse(data["auth_url"]).query)
    state = query["state"][0]

    assert query["client_id"] == ["custom-client.apps.googleusercontent.com"]
    assert routes._google_drive_oauth_states[state]["client_source"] == "custom_request"
    assert routes._google_drive_oauth_states[state]["client_secret"] == ""
    routes._google_drive_oauth_states.clear()


def test_google_drive_oauth_begin_custom_mode_without_client_returns_clear_error(client: TestClient, monkeypatch):
    routes._google_drive_oauth_states.clear()
    _patch_google_drive_config(monkeypatch)

    response = client.post("/api/http-download/google-drive/oauth-begin", json={
        "client_mode": "custom",
        "opener_origin": "http://localhost:5556",
    })

    assert response.status_code == 400
    assert "自定义 Google OAuth Client 需要填写 Client ID" in response.json()["detail"]


def test_google_drive_oauth_callback_exchanges_code_and_posts_message(client: TestClient, monkeypatch):
    routes._google_drive_oauth_states.clear()
    state = "state-for-test"
    routes._google_drive_oauth_states[state] = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code_verifier": "pkce-verifier",
        "redirect_uri": "http://testserver/api/http-download/google-drive/oauth-callback",
        "opener_origin": "http://localhost:5556",
        "created_at": time.time(),
    }

    async def fake_exchange_google_drive_authorization_code(**kwargs):
        assert kwargs == {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "authorization_code": "authorization-code",
            "redirect_uri": "http://testserver/api/http-download/google-drive/oauth-callback",
            "code_verifier": "pkce-verifier",
        }
        return {
            "success": True,
            "refresh_token": "refresh-token",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    monkeypatch.setattr(routes, "_exchange_google_drive_authorization_code", fake_exchange_google_drive_authorization_code)

    response = client.get("/api/http-download/google-drive/oauth-callback", params={
        "state": state,
        "code": "authorization-code",
    })

    assert response.status_code == 200
    body = response.text
    assert "kikoerumanager:google-drive-oauth" in body
    assert "refresh-token" in body
    assert "http://localhost:5556" in body
    assert state not in routes._google_drive_oauth_states


def test_google_drive_oauth_exchange_authorization_code_uses_proxy(monkeypatch):
    _patch_google_drive_config(monkeypatch, proxy_url="127.0.0.1:7890")
    captured = {"posts": [], "gets": []}

    class FakeResponse:
        def __init__(self, body, status=200):
            self._body = body
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def text(self):
            return self._body

    class FakeSession:
        def __init__(self, *_args, **kwargs):
            captured["session_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            captured["posts"].append({
                "url": url,
                "data": kwargs.get("data") or {},
                "proxy": kwargs.get("proxy"),
            })
            return FakeResponse(
                '{"refresh_token":"refresh-token","access_token":"access-token","scope":"scope","token_type":"Bearer","expires_in":3600}'
            )

        def get(self, url, **kwargs):
            captured["gets"].append({
                "url": url,
                "headers": kwargs.get("headers") or {},
                "proxy": kwargs.get("proxy"),
            })
            return FakeResponse(
                '{"user":{"displayName":"Elena","emailAddress":"elena@example.com","photoLink":"https://example.com/avatar.jpg","permissionId":"perm-1"}}'
            )

    monkeypatch.setattr("aiohttp.ClientSession", FakeSession)

    import asyncio

    result = asyncio.run(routes._exchange_google_drive_authorization_code(
        client_id="client-id",
        client_secret="",
        authorization_code="authorization-code",
        redirect_uri="http://localhost:5555/api/http-download/google-drive/oauth-callback",
        code_verifier="pkce-verifier",
    ))

    assert result["refresh_token"] == "refresh-token"
    assert result["account"]["cached_at"] > 0
    assert {key: result["account"][key] for key in ("name", "email", "avatar_url", "permission_id")} == {
        "name": "Elena",
        "email": "elena@example.com",
        "avatar_url": "https://example.com/avatar.jpg",
        "permission_id": "perm-1",
    }
    assert captured["posts"][0]["url"] == "https://oauth2.googleapis.com/token"
    assert captured["posts"][0]["data"]["code"] == "authorization-code"
    assert captured["posts"][0]["data"]["code_verifier"] == "pkce-verifier"
    assert captured["posts"][0]["proxy"] == "http://127.0.0.1:7890"
    assert captured["gets"][0]["url"].startswith("https://www.googleapis.com/drive/v3/about")
    assert captured["gets"][0]["headers"]["Authorization"] == "Bearer access-token"
    assert captured["gets"][0]["proxy"] == "http://127.0.0.1:7890"
