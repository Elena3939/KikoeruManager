from app.api import routes


def test_download_status_cache_reuses_same_version_within_ttl(monkeypatch):
    routes._DOWNLOAD_STATUS_CACHE.clear()
    monkeypatch.setattr(routes.time, "monotonic", lambda: 100.0)
    payload = {"tasks": [{"id": "task-1"}]}

    routes._download_status_cache_set("baidu_netdisk", 1, payload)

    assert routes._download_status_cache_get("baidu_netdisk", 1) == payload


def test_download_status_cache_rejects_fresh_payload_after_version_change(monkeypatch):
    routes._DOWNLOAD_STATUS_CACHE.clear()
    monkeypatch.setattr(routes.time, "monotonic", lambda: 100.0)
    routes._download_status_cache_set(
        "baidu_netdisk",
        1,
        {"tasks": [{"id": "old-task"}]},
    )

    assert routes._download_status_cache_get("baidu_netdisk", 2) is None


def test_download_status_cache_expires_same_version(monkeypatch):
    routes._DOWNLOAD_STATUS_CACHE.clear()
    now = [100.0]
    monkeypatch.setattr(routes.time, "monotonic", lambda: now[0])
    routes._download_status_cache_set("http_download", 3, {"tasks": []})

    now[0] += routes._DOWNLOAD_STATUS_CACHE_TTL_SECONDS + 0.01

    assert routes._download_status_cache_get("http_download", 3) is None
