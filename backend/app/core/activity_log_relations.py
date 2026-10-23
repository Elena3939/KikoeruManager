"""操作记录的身份与关联范围；批次分组不能代替任务父子关系。"""


IMPORT_CATEGORIES = {"auto_import", "process_existing", "extract"}
IMPORT_RESULT_ACTIONS = {"task_finished", "task_finished_incomplete", "extract_archive", "process_folder"}


def latest_import_results(rows):
    """同一任务重试只统计最新结果；审计明细仍保留所有尝试。"""
    latest = {}
    for row in rows:
        key = (row.get("category"), row.get("task_id") or row.get("id"))
        order = (str(row.get("created_at") or ""), str(row.get("id") or ""))
        previous = latest.get(key)
        if previous is None or order > (str(previous.get("created_at") or ""), str(previous.get("id") or "")):
            latest[key] = row
    return list(latest.values())


def normalize_import_summary(row):
    import re

    summary = str(row.get("summary") or "")
    if row.get("category") == "process_existing" and row.get("action") in IMPORT_RESULT_ACTIONS:
        return summary.replace("，耗时 ", "，总耗时 ")
    if row.get("category") in {"extract", "auto_import"} and row.get("action") in IMPORT_RESULT_ACTIONS:
        detail = row.get("detail") or {}
        summary = summary.removesuffix("，解压耗时未记录")
        summary = re.sub(r"，(?:总耗时|耗时|解压耗时|解压进程累计耗时|解包阶段耗时) [^，]*$", "", summary)
        if detail.get("extract_execution_duration_ms") is not None:
            from .activity_log_service import _format_duration_ms

            summary += f"，解压进程累计耗时 {_format_duration_ms(detail['extract_execution_duration_ms'])}"
        elif detail.get("extract_phase_duration_ms") is not None:
            from .activity_log_service import _format_duration_ms

            summary += f"，解包阶段耗时 {_format_duration_ms(detail['extract_phase_duration_ms'])}（含等待）"
        elif row.get("category") in {"extract", "auto_import"}:
            summary += "，解压耗时未记录"
    return summary


def is_import_batch_root(row) -> bool:
    return row.action == "batch_start"


def allows_group_relations(row) -> bool:
    if row.category not in IMPORT_CATEGORIES:
        return True
    return is_import_batch_root(row)


def find_activity_node(rows, log_id):
    """定位被聚合收进树里的原记录，保留用户点击的记录身份。"""
    for row in rows:
        if str(row.get("id")) == str(log_id):
            return row
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        match = find_activity_node(detail.get("child_rows") or [], log_id)
        if match is not None:
            return match
    return None
