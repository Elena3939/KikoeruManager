from app.core.log_sanitizer import REDACTED, mask_url_for_log, sanitize_for_log, sanitize_text_for_log


def test_sanitize_for_log_redacts_nested_config_values():
    payload = {
        "storage": {
            "synology_profiles": [
                {
                    "username": "Elena",
                    "password": "real-password",
                    "device_id": "device-token",
                    "base_url": "https://nas.example.com",
                }
            ]
        },
        "http_downloader": {
            "google_drive_refresh_token": "refresh-token",
            "pikpak_accounts": [{"account_id": "main", "encoded_token": "encoded"}],
        },
        "normal": "visible",
    }

    sanitized = sanitize_for_log(payload)

    assert sanitized["storage"]["synology_profiles"][0]["username"] == "Elena"
    assert sanitized["storage"]["synology_profiles"][0]["password"] == REDACTED
    assert sanitized["storage"]["synology_profiles"][0]["device_id"] == REDACTED
    assert sanitized["http_downloader"]["google_drive_refresh_token"] == REDACTED
    assert sanitized["http_downloader"]["pikpak_accounts"][0]["encoded_token"] == REDACTED
    assert sanitized["normal"] == "visible"


def test_sanitize_for_log_keeps_extract_password_fields_visible():
    payload = {
        "extract": {"password_list": ["zip-pass"]},
        "manual_retry_password": "retry-pass",
        "resolved_password": "resolved-pass",
        "password": "account-pass",
    }

    sanitized = sanitize_for_log(payload)

    assert sanitized["extract"]["password_list"] == ["zip-pass"]
    assert sanitized["manual_retry_password"] == "retry-pass"
    assert sanitized["resolved_password"] == "resolved-pass"
    assert sanitized["password"] == REDACTED


def test_sanitize_for_log_redacts_headers():
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer abc.def.secret",
        "Cookie": "BDUSS=abc; STOKEN=def",
    }

    sanitized = sanitize_for_log(headers)

    assert sanitized["Accept"] == "application/json"
    assert sanitized["Authorization"] == REDACTED
    assert sanitized["Cookie"] == REDACTED


def test_mask_url_for_log_masks_credentials_and_sensitive_query():
    url = "https://user:pass@example.com/path?token=abc&keyword=RJ12345678&refresh_token=def"

    masked = mask_url_for_log(url)

    assert "user:pass" not in masked
    assert "token=abc" not in masked
    assert "refresh_token=def" not in masked
    assert "***:***@example.com" in masked
    assert "keyword=RJ12345678" in masked


def test_sanitize_text_for_log_masks_inline_cookie_token_and_api_key():
    text = "Authorization: Bearer abcdefghijklmn Cookie=BDUSS=raw sk-testSecret123"

    sanitized = sanitize_text_for_log(text)

    assert "abcdefghijklmn" not in sanitized
    assert "BDUSS=raw" not in sanitized
    assert "sk-testSecret123" not in sanitized
    assert REDACTED in sanitized
