"""输入预检的配置凭据及临时目录准备上下文。"""

import hashlib
import json
from datetime import datetime
from contextvars import ContextVar


stage_preparer = ContextVar("input_scan_stage_preparer", default=None)


def policy_revision(config):
    values = {
        name: getattr(config, name).model_dump(mode="json")
        for name in ("auto_process", "metadata", "rename", "storage")
    }
    values["auto_classify"] = config.watcher.auto_classify
    return hashlib.sha256(json.dumps(
        values, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def index_view_token():
    from .linked_subtitle_import_service import get_linked_subtitle_import_service
    return get_linked_subtitle_import_service()._current_candidate_index_view_token()


def can_consume(task, config):
    """消费前核对源代次、身份及策略；过期或未知索引不作为免预检依据。"""
    from .input_stability import sample_sources
    from ..models.database import get_local_now
    metadata = task.task_metadata or {}
    evidence = metadata.get("input_preflight") or {}
    if evidence.get("version") != 1 or not evidence.get("proceed"):
        return False
    if evidence.get("policy_revision") != policy_revision(config):
        return False
    token = index_view_token()
    if token == "index-unavailable" or evidence.get("index_view_token") != token:
        return False
    try:
        age = (get_local_now() - datetime.fromisoformat(evidence["checked_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    if not 0 <= age <= 30:
        return False
    current_rj = str(metadata.get("rjcode") or getattr(task, "rjcode", "") or "")
    if current_rj and current_rj != evidence.get("rjcode"):
        return False
    fingerprints, reason = sample_sources(metadata.get("input_members") or [task.source_path])
    return not reason and fingerprints == evidence.get("fingerprints")
