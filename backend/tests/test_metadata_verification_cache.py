from datetime import datetime, timedelta

from app.core.dlsite_metadata_trust import attach_dlsite_metadata_verification
from app.core.metadata_service import MetadataService
from app.models.database import WorkMetadata


def _cached_metadata(**overrides):
    values = {
        "rjcode": "RJ01670873",
        "work_name": "【繁体中文版】怪異快楽",
        "maker_id": "RG64225",
        "maker_name": "生ハメ堕ち部★LACK",
        "release_date": "2026-07-25",
        "tags": [],
        "cvs": [],
        "metadata_verification_status": "verified",
        "metadata_verification_reason": "",
        "metadata_evidence_source": "page_embedded_original_match",
        "resolved_workno": "RJ01670873",
        "verified_parent_workno": "RJ01563471",
        "verified_parent_child_relation": True,
        "cached_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(days=30),
    }
    values.update(overrides)
    return WorkMetadata(**values)


def test_verified_translation_cache_keeps_parent_relation_evidence() -> None:
    cached = _cached_metadata()
    payload = cached.to_dict()
    payload["metadata_source"] = "cache"

    attach_dlsite_metadata_verification(payload, cached.rjcode)

    assert payload["metadata_verification_status"] == "verified"
    assert payload["metadata_evidence_source"] == "page_embedded_original_match"
    assert payload["maker_id"] == "RG64225"
    assert payload["maker_name"] == "生ハメ堕ち部★LACK"
    assert payload["verified_parent_workno"] == "RJ01563471"
    assert payload["verified_parent_child_relation"] is True


def test_legacy_cache_without_verification_evidence_is_refetched() -> None:
    cached = _cached_metadata(
        metadata_verification_status="unverified",
        metadata_evidence_source="",
        verified_parent_workno="",
        verified_parent_child_relation=False,
    )

    assert MetadataService()._should_refresh_cached_metadata(cached) is True


def test_verified_normal_product_cache_can_be_reused() -> None:
    cached = _cached_metadata(
        rjcode="RJ01563471",
        metadata_evidence_source="dlsite_product",
        resolved_workno="RJ01563471",
        verified_parent_workno="",
        verified_parent_child_relation=False,
    )

    assert MetadataService()._should_refresh_cached_metadata(cached) is False
