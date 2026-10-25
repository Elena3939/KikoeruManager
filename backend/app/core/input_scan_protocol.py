"""持久扫描批次的结算栅栏；旧版本批次保留原有口径。"""


def scan_batch_status(detail):
    if not isinstance(detail, dict) or detail.get("schema_version") != 2 or not detail.get("scan_id"):
        return None
    if (not detail.get("producer_closed") or not detail.get("scan_closed")
            or detail.get("execution_status") in {"not_started", "running", "waiting", None}):
        return "incomplete"
    return {
        "success": "success", "empty": "success", "partial": "partial_success",
        "failed": "failed", "cancelled": "cancelled",
    }.get(detail.get("execution_status"), "incomplete")
