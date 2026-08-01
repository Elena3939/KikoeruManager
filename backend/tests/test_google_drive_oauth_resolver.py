from types import SimpleNamespace

from app.core.google_drive_oauth import (
    DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID,
    DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET,
    google_drive_oauth_client_missing_message,
    resolve_google_drive_oauth_client,
    resolve_google_drive_oauth_proxy_url,
)


_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def _clear_proxy_env(monkeypatch):
    for key in _PROXY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _config(metadata_http_proxy="", **values):
    defaults = {
        "google_drive_oauth_client_mode": "builtin",
        "google_drive_client_id": "",
        "google_drive_client_secret": "",
        "google_drive_refresh_token": "",
        "proxy_url": "",
    }
    defaults.update(values)
    return SimpleNamespace(
        http_downloader=SimpleNamespace(**defaults),
        metadata=SimpleNamespace(http_proxy=metadata_http_proxy),
    )


def test_resolve_google_drive_oauth_client_uses_builtin_env(monkeypatch):
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", "builtin-client")
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_SECRET", "builtin-secret")

    client = resolve_google_drive_oauth_client(config=_config())

    assert client.client_id == "builtin-client"
    assert client.client_secret == "builtin-secret"
    assert client.source == "builtin"
    assert client.mode == "builtin"


def test_resolve_google_drive_oauth_client_custom_request_overrides_builtin(monkeypatch):
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", "builtin-client")

    client = resolve_google_drive_oauth_client(
        config=_config(),
        mode="custom",
        client_id="custom-client",
        client_secret="custom-secret",
    )

    assert client.client_id == "custom-client"
    assert client.client_secret == "custom-secret"
    assert client.source == "custom_request"
    assert client.mode == "custom"


def test_resolve_google_drive_oauth_client_uses_saved_custom_in_custom_mode(monkeypatch):
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", raising=False)

    client = resolve_google_drive_oauth_client(
        config=_config(
            google_drive_client_id="saved-client",
            google_drive_client_secret="saved-secret",
        ),
        mode="custom",
    )

    assert client.client_id == "saved-client"
    assert client.client_secret == "saved-secret"
    assert client.source == "custom_saved"
    assert client.mode == "custom"


def test_resolve_google_drive_oauth_client_uses_default_builtin_without_env(monkeypatch):
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CLIENT_SECRET", raising=False)

    client = resolve_google_drive_oauth_client(config=_config())

    assert client.client_id == DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID
    assert client.client_secret == DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET
    assert client.source == "builtin"
    assert client.mode == "builtin"


def test_resolve_google_drive_oauth_client_does_not_pair_default_secret_with_env_client(monkeypatch):
    monkeypatch.setenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID", "env-client.apps.googleusercontent.com")
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CLIENT_SECRET", raising=False)

    client = resolve_google_drive_oauth_client(config=_config())

    assert client.client_id == "env-client.apps.googleusercontent.com"
    assert client.client_secret == ""


def test_google_drive_oauth_client_missing_message_mentions_builtin_env():
    message = google_drive_oauth_client_missing_message("builtin")

    assert "内置 Google OAuth 应用不可用" in message
    assert "KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID" in message


def test_resolve_google_drive_oauth_proxy_prefers_http_downloader_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:9000")

    proxy = resolve_google_drive_oauth_proxy_url(_config(
        proxy_url="127.0.0.1:7891",
        metadata_http_proxy="127.0.0.1:7890",
    ))

    assert proxy == "http://127.0.0.1:7891"


def test_resolve_google_drive_oauth_proxy_falls_back_to_metadata_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)

    proxy = resolve_google_drive_oauth_proxy_url(_config(metadata_http_proxy="127.0.0.1:7890"))

    assert proxy == "http://127.0.0.1:7890"


def test_resolve_google_drive_oauth_proxy_uses_environment_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:7892")

    proxy = resolve_google_drive_oauth_proxy_url(_config())

    assert proxy == "http://127.0.0.1:7892"


def test_resolve_google_drive_oauth_proxy_ignores_disabled_value_without_fallback(monkeypatch):
    _clear_proxy_env(monkeypatch)

    proxy = resolve_google_drive_oauth_proxy_url(_config(proxy_url="direct"))

    assert proxy == ""
