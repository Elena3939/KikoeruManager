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
    summary = str(row.get("summary") or "")
    if row.get("category") in IMPORT_CATEGORIES and row.get("action") in IMPORT_RESULT_ACTIONS:
        summary = summary.replace("，耗时 ", "，总耗时 ")
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
