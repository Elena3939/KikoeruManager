from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import routes
from app.core import baidu_netdisk_service


def _disable_security_gate(monkeypatch):
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


def test_baidu_netdisk_account_refresh_forces_remote_account_sync(client: TestClient, monkeypatch):
    _disable_security_gate(monkeypatch)
    calls = []

    class FakeBaiduNetdiskService:
        async def refresh_account_status(self):
            calls.append("refresh")
            return {
                "success": True,
                "message": "百度账号状态已刷新",
                "official_login": {"active": False},
                "account": {
                    "enabled": True,
                    "configured": True,
                    "ready": True,
                    "name": "tester",
                    "quota_bytes": 2 * 1024**4,
                    "used_bytes": 1024**4,
                    "remaining_bytes": 1024**4,
                    "cached_at": 1717400000,
                },
            }

    monkeypatch.setattr(
        baidu_netdisk_service,
        "get_baidu_netdisk_service",
        lambda: FakeBaiduNetdiskService(),
    )

    response = client.post("/api/baidu-netdisk/account/refresh")

    assert response.status_code == 200
    assert calls == ["refresh"]
    data = response.json()
    assert data["account"]["quota_bytes"] == 2 * 1024**4
    assert data["account"]["remaining_bytes"] == 1024**4
