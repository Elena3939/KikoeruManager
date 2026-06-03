import os
from dataclasses import dataclass
from typing import Any, Optional


GOOGLE_DRIVE_OAUTH_CLIENT_ID_ENV = "KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_ID"
GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_ENV = "KIKOERUMANAGER_GOOGLE_DRIVE_CLIENT_SECRET"
DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID = "202264815644.apps.googleusercontent.com"
DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET = "X4Z3ca8xfWDb1Voo-F9a7ZxJ"

_CLIENT_ID_ENV_ALIASES = (
    GOOGLE_DRIVE_OAUTH_CLIENT_ID_ENV,
    "KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_DRIVE_OAUTH_CLIENT_ID",
)
_CLIENT_SECRET_ENV_ALIASES = (
    GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_ENV,
    "KIKOERUMANAGER_GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_DRIVE_OAUTH_CLIENT_SECRET",
)
_PROXY_ENV_ALIASES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


@dataclass(frozen=True)
class GoogleDriveOAuthClient:
    client_id: str
    client_secret: str = ""
    source: str = "custom"
    mode: str = "custom"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_secret(value: Any) -> str:
    text = _clean(value)
    return "" if text == "********" else text


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = _clean(os.environ.get(name))
        if value:
            return value
    return ""


def normalize_google_drive_proxy_url(value: Any) -> str:
    text = _clean(value)
    if not text or text.lower() in {"0", "false", "none", "off", "direct"}:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return text


def resolve_google_drive_oauth_proxy_url(config: Any = None) -> str:
    http_downloader = getattr(config, "http_downloader", None) or config
    proxy = normalize_google_drive_proxy_url(getattr(http_downloader, "proxy_url", ""))
    if proxy:
        return proxy

    metadata = getattr(config, "metadata", None)
    proxy = normalize_google_drive_proxy_url(getattr(metadata, "http_proxy", ""))
    if proxy:
        return proxy

    return normalize_google_drive_proxy_url(_first_env(_PROXY_ENV_ALIASES))


def normalize_google_drive_oauth_client_mode(value: Any) -> str:
    text = _clean(value).lower()
    if text in {"custom", "user", "advanced", "self"}:
        return "custom"
    return "builtin"


def _builtin_google_drive_oauth_client() -> Optional[GoogleDriveOAuthClient]:
    env_client_id = _first_env(_CLIENT_ID_ENV_ALIASES)
    client_id = env_client_id or DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID
    if not client_id:
        return None
    client_secret = _first_env(_CLIENT_SECRET_ENV_ALIASES)
    if not env_client_id and client_id == DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_ID and not client_secret:
        client_secret = DEFAULT_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET
    return GoogleDriveOAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        source="builtin",
        mode="builtin",
    )


def _configured_google_drive_oauth_client(config: Any) -> Optional[GoogleDriveOAuthClient]:
    http_downloader = getattr(config, "http_downloader", None) or config
    client_id = _clean(getattr(http_downloader, "google_drive_client_id", ""))
    if not client_id:
        return None
    return GoogleDriveOAuthClient(
        client_id=client_id,
        client_secret=_clean_secret(getattr(http_downloader, "google_drive_client_secret", "")),
        source="custom_saved",
        mode="custom",
    )


def resolve_google_drive_oauth_client(
    *,
    config: Any = None,
    mode: Any = "",
    client_id: Any = "",
    client_secret: Any = "",
) -> Optional[GoogleDriveOAuthClient]:
    resolved_mode = normalize_google_drive_oauth_client_mode(mode)
    request_client_id = _clean(client_id)
    request_client_secret = _clean_secret(client_secret)

    if request_client_id:
        return GoogleDriveOAuthClient(
            client_id=request_client_id,
            client_secret=request_client_secret,
            source="custom_request",
            mode="custom",
        )

    saved_client = _configured_google_drive_oauth_client(config)
    if resolved_mode == "custom":
        return saved_client

    builtin_client = _builtin_google_drive_oauth_client()
    if builtin_client:
        return builtin_client

    return saved_client


def google_drive_oauth_client_missing_message(mode: Any = "") -> str:
    if normalize_google_drive_oauth_client_mode(mode) == "custom":
        return "自定义 Google OAuth Client 需要填写 Client ID；Client Secret 可留空，Web 类型客户端才需要 Secret。"
    return (
        "内置 Google OAuth 应用不可用。"
        f"请设置环境变量 {GOOGLE_DRIVE_OAUTH_CLIENT_ID_ENV}，"
        "或在高级设置里切到自定义 OAuth Client。"
    )
