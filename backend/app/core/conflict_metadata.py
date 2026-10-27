"""问题作品列表与按需诊断的元数据投影，不修改持久化内容。"""

import contextlib
import json

from .json_safety import safe_json_value


CONFLICT_DIAGNOSTIC_FIELDS = frozenset({
    "extract_timing", "progress_log", "linked_subtitle_preview",
    "input_preflight", "input_stability", "source_stats_cache",
    "metadata_prefetch", "file_tree_items", "filtered_files",
    "filtered_dirs", "filtered_items", "download_files", "upload_files",
    "uploaded_files", "raw_metadata",
})


def parse_conflict_metadata(raw_metadata) -> dict:
    """只解析结构；输出投影完成后再清洗，避免遍历不需要返回的大字段。"""
    if isinstance(raw_metadata, dict):
        return raw_metadata
    if raw_metadata in (None, "", []):
        return {}
    if isinstance(raw_metadata, str):
        with contextlib.suppress(ValueError, TypeError):
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                return parsed
    if not isinstance(raw_metadata, (str, list)):
        with contextlib.suppress(TypeError, ValueError):
            return dict(raw_metadata)
    return {"raw_metadata": raw_metadata}


def conflict_list_metadata(metadata: dict) -> dict:
    return safe_json_value({
        key: value for key, value in metadata.items()
        if key not in CONFLICT_DIAGNOSTIC_FIELDS
    })


def conflict_diagnostic_metadata(metadata: dict) -> dict:
    return safe_json_value({
        key: value for key, value in metadata.items()
        if key in CONFLICT_DIAGNOSTIC_FIELDS
    })
