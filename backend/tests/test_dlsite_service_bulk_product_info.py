import pytest

from app.core.dlsite_service import DLsiteApiService


def _service() -> DLsiteApiService:
    return DLsiteApiService.__new__(DLsiteApiService)


@pytest.mark.asyncio
async def test_probe_product_info_features_uses_bulk_product_info_request() -> None:
    service = _service()
    calls: list[str] = []

    async def fake_fetch_api(url: str):
        calls.append(url)
        return {
            "RJ000001": {
                "maker_id": "RG1",
                "regist_date": "2026-01-01",
                "work_type": "SOU",
                "price": 0,
                "is_sale": False,
                "is_free": True,
                "is_oly": True,
                "wishlist_count": 0,
            },
            "RJ000002": {
                "maker_id": "RG2",
                "regist_date": "2026-01-02",
                "work_type": "SOU",
                "price": 110,
            },
        }

    service._fetch_api = fake_fetch_api

    features = await service.probe_product_info_features(["RJ000001", "RJ000002"], concurrency=1)

    assert len(calls) == 1
    assert "product_id=RJ000001,RJ000002" in calls[0]
    assert features["RJ000001"].exists is True
    assert features["RJ000001"].is_hidden_bonus_audio is True
    assert features["RJ000002"].exists is True
    assert features["RJ000002"].is_hidden_bonus_audio is False


@pytest.mark.asyncio
async def test_probe_product_info_features_marks_missing_items_from_bulk_response() -> None:
    service = _service()

    async def fake_fetch_api(url: str):
        return {
            "RJ000001": {
                "maker_id": "RG1",
                "regist_date": "2026-01-01",
                "work_type": "SOU",
                "price": 110,
            },
        }

    service._fetch_api = fake_fetch_api

    features = await service.probe_product_info_features(["RJ000001", "RJ000099"], concurrency=1)

    assert features["RJ000001"].exists is True
    assert features["RJ000099"].exists is False
    assert features["RJ000099"].probe_status == "missing"
