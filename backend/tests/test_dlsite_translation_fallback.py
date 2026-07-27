from unittest.mock import AsyncMock

import pytest

from app.core.dlsite_service import DLsiteApiService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "parent", "title", "expected_lang"),
    [
        (
            "RJ01606254",
            "RJ01606253",
            "【簡体中文版】テスト作品 [みんなで翻訳]",
            "CHI_HANS",
        ),
        (
            "RJ01583281",
            "RJ01583280",
            "【繁體中文版】テスト作品 [みんなで翻訳]",
            "CHI_HANT",
        ),
    ],
)
async def test_translation_info_uses_explicit_page_fallback_parent(
    requested,
    parent,
    title,
    expected_lang,
):
    service = DLsiteApiService()
    service.get_product_info = AsyncMock(return_value={
        "product": {"work_name": title, "translation_info": {}},
        "requested_workno": requested,
        "resolved_workno": parent,
        "parent_workno": parent,
        "fallback_source": "page_metadata",
    })

    result = await service.get_translation_info(requested)

    assert result.is_child is True
    assert result.parent_workno == parent
    assert result.original_workno == parent
    assert result.lang == expected_lang


@pytest.mark.asyncio
async def test_translation_title_without_parent_remains_unverified():
    service = DLsiteApiService()
    service.get_product_info = AsyncMock(return_value={
        "product": {
            "work_name": "【簡体中文版】テスト作品 [みんなで翻訳]",
            "translation_info": {},
        },
        "requested_workno": "RJ01609999",
        "resolved_workno": "RJ01609999",
        "parent_workno": "",
        "fallback_source": "page_metadata",
    })

    result = await service.get_translation_info("RJ01609999")

    assert result.is_original is False
    assert result.is_parent is False
    assert result.is_child is False
    assert result.original_workno is None
    assert result.parent_workno is None
    assert result.lang == ""
    assert "RJ01609999" not in service._translation_info_cache


@pytest.mark.asyncio
async def test_normal_product_without_translation_linkage_keeps_default_result():
    service = DLsiteApiService()
    service.get_product_info = AsyncMock(return_value={
        "product": {
            "work_name": "通常の日本語作品",
            "translation_info": {},
        },
        "requested_workno": "RJ01608888",
        "resolved_workno": "RJ01608888",
        "parent_workno": "",
        "fallback_source": "api",
    })

    result = await service.get_translation_info("RJ01608888")

    assert result.is_original is False
    assert result.is_parent is False
    assert result.is_child is False
    assert result.lang == "JPN"
    assert "RJ01608888" in service._translation_info_cache


@pytest.mark.asyncio
async def test_explicit_api_translation_info_wins_over_page_fallback():
    service = DLsiteApiService()
    service.get_product_info = AsyncMock(return_value={
        "product": {
            "translation_info": {
                "is_original": True,
                "lang": "JPN",
            }
        },
        "parent_workno": "RJ01600000",
        "fallback_source": "page_metadata",
    })

    result = await service.get_translation_info("RJ01600001")

    assert result.is_original is True
    assert result.is_child is False
    assert result.original_workno is None
    assert result.lang == "JPN"
