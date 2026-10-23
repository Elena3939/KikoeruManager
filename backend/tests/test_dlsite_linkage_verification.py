"""关联证据与命名元数据隔离，以及不完整关联缓存的回归。"""

from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.dlsite_metadata_trust import is_dlsite_linkage_product_verified
from app.core.dlsite_service import DLsiteApiService, LinkedWork
from app.core.import_validation import ImportDataError, require_complete_linkage


def api_product(rj, translation, **extra):
    return {
        "product": {
            "workno": rj,
            "maker_name": "みんなで翻訳",
            "translation_info": translation,
            **extra,
        },
        "requested_workno": rj,
        "resolved_workno": rj,
        "fallback_source": "api",
        "metadata_evidence_source": "dlsite_product",
        "metadata_verification_status": "unverified",
        "metadata_verification_reason": "社团名是翻译占位名: みんなで翻訳",
    }


@pytest.mark.asyncio
async def test_official_child_relations_survive_placeholder_maker():
    service = DLsiteApiService()
    original, parent, requested, sibling = (
        "RJ01112047", "RJ01591868", "RJ01724536", "RJ01655869"
    )
    traditional_parent, traditional_child = "RJ01724537", "RJ01724538"
    payloads = {
        original: api_product(original, {"is_original": True}, language_editions=[
            {"workno": parent, "lang": "CHI_HANS"},
            {"workno": traditional_parent, "lang": "CHI_HANT"},
        ]),
        parent: api_product(parent, {
            "is_parent": True, "original_workno": original,
            "child_worknos": [requested, sibling], "lang": "CHI_HANS",
        }),
        requested: api_product(requested, {
            "is_child": True, "original_workno": original,
            "parent_workno": parent, "lang": "CHI_HANS",
        }),
        # 旁支自身没有可用详情，但官方父作品明确列出了它。
        sibling: {},
        traditional_parent: api_product(traditional_parent, {
            "is_parent": True, "original_workno": original,
            "child_worknos": [traditional_child], "lang": "CHI_HANT",
        }),
        traditional_child: {},
    }
    before = deepcopy(payloads)
    service.get_product_info = AsyncMock(side_effect=lambda rj: payloads[rj])

    works = await service.get_linked_works(requested)

    assert set(works) == {
        original, parent, requested, sibling, traditional_parent, traditional_child,
    }
    require_complete_linkage(works)
    assert works[sibling].work_type == "child_translation"
    assert works[traditional_child].evidence_status == "verified"
    assert service.cache[f"linked_works:{requested}"]["ttl_seconds"] == 86400
    assert payloads == before  # 命名元数据仍然未经验证，不能借此放行命名。


@pytest.mark.parametrize("kind", ["mismatch", "page_guess", "missing_edition"])
def test_inferred_or_mismatched_product_is_not_verified(kind):
    payload = api_product("RJ01724536", {"is_original": True})
    if kind == "mismatch":
        payload["resolved_workno"] = "RJ01112047"
    elif kind == "page_guess":
        payload["fallback_source"] = "page_metadata"
        payload["metadata_evidence_source"] = "page_metadata_unverified"
    else:
        payload["resolved_workno"] = "RJ01591868"
        payload["parent_workno"] = "RJ01591868"
        payload["fallback_source"] = "translation_page"
    assert not is_dlsite_linkage_product_verified(payload, "RJ01724536")


def test_exact_parent_language_edition_is_verified_without_maker():
    payload = api_product("RJ01724536", {"is_child": True})
    payload.update({
        "resolved_workno": "RJ01591868", "parent_workno": "RJ01591868",
        "fallback_source": "translation_page",
        "edition_info": {"workno": "RJ01724536"},
    })
    assert is_dlsite_linkage_product_verified(payload, "RJ01724536")
    payload["edition_info"] = {"workno": "RJ01724537"}
    assert not is_dlsite_linkage_product_verified(payload, "RJ01724536")


@pytest.mark.asyncio
async def test_partial_linkage_does_not_keep_old_day_cache():
    service = DLsiteApiService()
    mixed = {
        "RJ01112047": LinkedWork("RJ01112047", "original", evidence_status="verified"),
        "RJ01724536": LinkedWork("RJ01724536", "unknown"),
    }
    key = "linked_works:RJ01724536"
    service.cache[key] = {
        "data": mixed, "timestamp": datetime.now() - timedelta(minutes=6),
        "ttl_seconds": 86400,
    }
    service._compute_linked_works = AsyncMock(return_value=mixed)

    result = await service.get_linked_works("RJ01724536")

    service._compute_linked_works.assert_awaited_once()
    assert service.cache[key]["ttl_seconds"] == 300
    with pytest.raises(ImportDataError):
        require_complete_linkage(result)


@pytest.mark.asyncio
async def test_full_linkage_strict_read_cannot_bypass_validation_via_cache():
    service = DLsiteApiService()
    service.get_translation_info = AsyncMock()
    service.get_translation_info.return_value.is_original = True
    service.cache["RJ01724536_CHI_HANS_CHI_HANT"] = {
        "data": {"RJ01724536": LinkedWork("RJ01724536", "unknown")},
        "timestamp": datetime.now(),
    }
    with pytest.raises(ImportDataError):
        await service.get_full_linkage("RJ01724536", require_verified=True)
