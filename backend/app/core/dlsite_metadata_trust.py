import re
from typing import Any, Dict


_PLACEHOLDER_MAKER_MARKERS = (
    "みんなで翻訳",
    "みんなで翻译",
    "大家一起来翻译",
    "大家一起翻译",
    "everyone translation",
)

_UNVERIFIED_EVIDENCE_SOURCES = {
    "",
    "unknown",
    "cache",
    "legacy",
    "legacy_cache",
    "minimal",
    "page_metadata",
    "page_metadata_unverified",
}

_RELATION_EVIDENCE_SOURCES = {
    "language_editions",
    "translation_info",
    "translation_page",
}


def normalize_rjcode(value: Any) -> str:
    match = re.search(r"RJ\d{4,12}", str(value or ""), re.IGNORECASE)
    return match.group(0).upper() if match else ""


def is_translation_placeholder_maker(value: Any) -> bool:
    folded = str(value or "").strip().casefold()
    if not folded:
        return False
    if any(marker.casefold() in folded for marker in _PLACEHOLDER_MAKER_MARKERS):
        return True
    return bool(re.search(r"(^|[\s_\-])translation([\s_\-]|$)", folded))


def assess_dlsite_metadata(
    metadata: Dict[str, Any],
    requested_rjcode: Any,
) -> Dict[str, str]:
    requested = normalize_rjcode(requested_rjcode)
    resolved = normalize_rjcode(
        metadata.get("resolved_workno")
        or metadata.get("workno")
        or metadata.get("rjcode")
    )
    maker_name = str(
        metadata.get("original_maker_name")
        or metadata.get("classification_maker_name")
        or metadata.get("maker_name")
        or ""
    ).strip()
    evidence_source = str(
        metadata.get("metadata_evidence_source")
        or metadata.get("fallback_source")
        or metadata.get("metadata_source")
        or ""
    ).strip().lower()
    parent = normalize_rjcode(
        metadata.get("verified_parent_workno")
        or metadata.get("parent_workno")
        or metadata.get("original_workno")
    )
    relation_verified = bool(metadata.get("verified_parent_child_relation"))

    if not requested:
        return {
            "status": "unverified",
            "reason": "请求 RJ 无效",
            "evidence_source": evidence_source or "unknown",
        }
    if evidence_source in _UNVERIFIED_EVIDENCE_SOURCES:
        return {
            "status": "unverified",
            "reason": "元数据来源缺少可验证的结构化证据",
            "evidence_source": evidence_source or "unknown",
        }
    if is_translation_placeholder_maker(maker_name):
        return {
            "status": "unverified",
            "reason": f"社团名是翻译占位名: {maker_name}",
            "evidence_source": evidence_source or "unknown",
        }
    if evidence_source in _RELATION_EVIDENCE_SOURCES and not relation_verified:
        return {
            "status": "unverified",
            "reason": "翻译版元数据缺少已验证的父子关系",
            "evidence_source": evidence_source,
        }
    if resolved == requested:
        return {
            "status": "verified",
            "reason": "",
            "evidence_source": evidence_source or "dlsite_product",
        }
    if relation_verified and parent and resolved in {parent, requested}:
        return {
            "status": "verified",
            "reason": "",
            "evidence_source": evidence_source or "language_editions",
        }
    return {
        "status": "unverified",
        "reason": f"返回 workno 与请求 RJ 不一致: requested={requested} resolved={resolved or 'missing'}",
        "evidence_source": evidence_source or "unknown",
    }


def attach_dlsite_metadata_verification(
    metadata: Dict[str, Any],
    requested_rjcode: Any,
) -> Dict[str, Any]:
    result = assess_dlsite_metadata(metadata, requested_rjcode)
    metadata["metadata_verification_status"] = result["status"]
    metadata["metadata_verification_reason"] = result["reason"]
    metadata["metadata_evidence_source"] = result["evidence_source"]
    return metadata
