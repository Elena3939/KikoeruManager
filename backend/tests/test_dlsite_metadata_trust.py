import asyncio

import pytest

from app.core.dlsite_metadata_trust import assess_dlsite_metadata
from app.core.dlsite_service import DLsiteApiService


def test_legacy_cache_never_passes_metadata_gate() -> None:
    result = assess_dlsite_metadata(
        {
            "rjcode": "RJ01619668",
            "maker_name": "正常社团",
            "metadata_evidence_source": "legacy_cache",
        },
        "RJ01619668",
    )

    assert result["status"] == "unverified"
    assert "结构化证据" in result["reason"]


@pytest.mark.parametrize("source", ["page_metadata", "page_metadata_unverified"])
def test_page_metadata_never_passes_metadata_gate(source: str) -> None:
    result = assess_dlsite_metadata(
        {
            "rjcode": "RJ01619668",
            "maker_name": "正常社团",
            "metadata_evidence_source": source,
        },
        "RJ01619668",
    )

    assert result["status"] == "unverified"


def test_translation_page_requires_verified_parent_child_relation() -> None:
    result = assess_dlsite_metadata(
        {
            "resolved_workno": "RJ01619667",
            "verified_parent_workno": "RJ01619667",
            "maker_name": "正常社团",
            "metadata_evidence_source": "translation_page",
        },
        "RJ01619668",
    )

    assert result["status"] == "unverified"
    assert "父子关系" in result["reason"]


def test_language_editions_can_verify_parent_child_relation() -> None:
    result = assess_dlsite_metadata(
        {
            "resolved_workno": "RJ01619667",
            "verified_parent_workno": "RJ01619667",
            "verified_parent_child_relation": True,
            "maker_name": "正常社团",
            "metadata_evidence_source": "language_editions",
        },
        "RJ01619668",
    )

    assert result["status"] == "verified"


def test_translation_placeholder_maker_never_passes_metadata_gate() -> None:
    result = assess_dlsite_metadata(
        {
            "rjcode": "RJ01619668",
            "maker_name": "みんなで翻訳",
            "metadata_evidence_source": "dlsite_product",
        },
        "RJ01619668",
    )

    assert result["status"] == "unverified"
    assert "翻译占位名" in result["reason"]


@pytest.mark.asyncio
async def test_product_info_cache_uses_result_specific_ttls(monkeypatch) -> None:
    service = DLsiteApiService()

    async def missing_product(_rjcode, locale=None):
        return None

    async def no_translation_fallback(_rjcode, locale=None):
        return {}

    async def page_metadata(rjcode, locale=None):
        return {
            "workno": rjcode,
            "work_name": "页面标题",
            "maker_name": "页面社团",
        }

    monkeypatch.setattr(service, "_fetch_product_payload", missing_product)
    monkeypatch.setattr(
        service,
        "_resolve_translation_page_fallback",
        no_translation_fallback,
    )
    monkeypatch.setattr(service, "_fetch_product_page_metadata", page_metadata)

    await service.get_product_info("RJ01610001")
    page_entry = service.cache["product_info:RJ01610001:"]
    assert page_entry["ttl_seconds"] == 900
    assert page_entry["data"]["metadata_verification_status"] == "unverified"

    async def no_page_metadata(_rjcode, locale=None):
        return None

    monkeypatch.setattr(service, "_fetch_product_page_metadata", no_page_metadata)
    await service.get_product_info("RJ01610002")
    failure_entry = service.cache["product_info:RJ01610002:"]
    assert failure_entry["ttl_seconds"] == 300
    assert failure_entry["data"] is None

    async def verified_product(rjcode, locale=None):
        return {
            "workno": rjcode,
            "work_name": "结构化标题",
            "maker_name": "结构化社团",
        }

    monkeypatch.setattr(service, "_fetch_product_payload", verified_product)
    await service.get_product_info("RJ01610003")
    success_entry = service.cache["product_info:RJ01610003:"]
    assert success_entry["ttl_seconds"] == 86400
    assert success_entry["data"]["metadata_verification_status"] == "verified"


@pytest.mark.asyncio
async def test_force_refresh_keeps_product_info_inflight_singleflight(monkeypatch) -> None:
    service = DLsiteApiService()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def verified_product(rjcode, locale=None):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {
            "workno": rjcode,
            "work_name": "结构化标题",
            "maker_name": "结构化社团",
        }

    monkeypatch.setattr(service, "_fetch_product_payload", verified_product)

    first = asyncio.create_task(
        service.get_product_info("RJ01610004", refresh=True)
    )
    await started.wait()
    second = asyncio.create_task(
        service.get_product_info("RJ01610004", refresh=True)
    )
    await asyncio.sleep(0)
    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert calls == 1
    assert first_result == second_result
    assert first_result["metadata_verification_status"] == "verified"
