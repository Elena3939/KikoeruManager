"""翻译占位社团不能阻断已验证的原作查询，也不能放宽作品信任边界。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.metadata_service import MetadataService


@pytest.mark.asyncio
@pytest.mark.parametrize("source,workno,original_verified,accepted", [
    ("dlsite_product", "RJ01116988", True, True),
    ("page_embedded_product", "RJ01116988", True, True),
    ("page_metadata_unverified", "RJ01116988", True, False),
    ("dlsite_product", "RJ09999999", True, False),
    ("dlsite_product", "RJ01116988", False, False),
])
async def test_translated_metadata_resolves_verified_original(
    monkeypatch, source, workno, original_verified, accepted,
):
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: SimpleNamespace(
        metadata=SimpleNamespace(sleep_interval=0),
    ))
    service = MetadataService()
    fetch = AsyncMock(side_effect=[{
        "metadata_verification_status": "unverified",
        "metadata_evidence_source": source,
        "product": {
            "workno": workno, "maker_name": "みんなで翻訳",
            "translation_info": {"is_original": False, "original_workno": "RJ01043646"},
        },
    }, {
        "metadata_verification_status": "verified" if original_verified else "unverified",
        "product": {
            "workno": "RJ01043646", "maker_name": "舌ノ音工房",
            "translation_info": {"is_original": True},
            "creaters": {"voice_by": [{"name": "原作声优"}]},
        },
    }])
    monkeypatch.setattr(service, "_get_product_info_for_metadata", fetch)
    result = await service.fetch_japanese_metadata("RJ01116988", force_refresh=True)
    if accepted:
        assert result["original_maker_name"] == "舌ノ音工房"
        assert result["cvs"] == ["原作声优"]
        assert fetch.await_args.args == ("RJ01043646",)
        assert fetch.await_args.kwargs["refresh"] is True
    else:
        assert result is None
