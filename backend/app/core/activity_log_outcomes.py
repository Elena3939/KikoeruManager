"""业务结果与执行状态分开：重复排除不是解压失败，旧审计记录不回写。"""
from .activity_log_relations import IMPORT_CATEGORIES, IMPORT_RESULT_ACTIONS


DUPLICATE_TEXTS = (
    "重复作品", "原作目录已有字幕", "原作已在 Kikoeru 端有字幕",
    "发现直接重复，请在问题作品页面处理", "发现原作已存在，请在问题作品页面处理",
    "发现翻译版已存在，请在问题作品页面处理", "发现子版本已存在，请在问题作品页面处理",
    "发现关联作品，请在问题作品页面处理", "发现语言变体，请在问题作品页面处理",
    "发现多版本，请在问题作品页面处理", "正在处理中，请在问题作品页面查看",
)
DUPLICATE_MODES = (
    "linked_translation_archive_existing_subtitle_conflict",
    "linked_translation_archive_existing_subtitle_skipped",
)
HANDLED_STATUSES = ("success", "completed", "partial_success", "waiting")
EXTRACT_FAILURE_TEXT = "解压失败，已加入问题作品列表"


def import_result_status(row):
    """人工处理状态不代表执行结果；明确失败优先于重复排除。"""
    status = str(row.get("status") or "")
    detail = row.get("detail") or {}
    if (row.get("category") in IMPORT_CATEGORIES
            and row.get("action") in IMPORT_RESULT_ACTIONS
            and status in HANDLED_STATUSES
            and (detail.get("business_outcome") == "failed"
                 or EXTRACT_FAILURE_TEXT in str(row.get("summary") or ""))):
        return "failed"
    if (row.get("category") in IMPORT_CATEGORIES
            and row.get("action") in IMPORT_RESULT_ACTIONS
            and status in HANDLED_STATUSES
            and not detail.get("conflict_resolution_action")
            and (detail.get("business_outcome") == "duplicate"
                 or detail.get("source_mode") in DUPLICATE_MODES
                 or any(text in str(row.get("summary") or "") for text in DUPLICATE_TEXTS))):
        return "success"
    return status


def is_duplicate_result(row):
    detail = row.get("detail") or {}
    return (import_result_status(row) == "success" and row.get("category") in IMPORT_CATEGORIES
            and row.get("action") in IMPORT_RESULT_ACTIONS
            and not detail.get("conflict_resolution_action")
            and (detail.get("business_outcome") == "duplicate"
                 or detail.get("source_mode") in DUPLICATE_MODES
                 or any(text in str(row.get("summary") or "") for text in DUPLICATE_TEXTS)))


def is_subtitle_handoff(row):
    """任务已移交补配工作台，不能把它标成已入库或解压失败。"""
    return (row.get("category") in IMPORT_CATEGORIES
            and row.get("action") in IMPORT_RESULT_ACTIONS
            and row.get("status") in {"success", "completed"}
            and (row.get("detail") or {}).get("source_mode") == "linked_translation_archive_pending")


def sql_import_result_status(model):
    """状态筛选和当前页 Python 汇总共用相同证据及优先级。"""
    from sqlalchemy import and_, case, func, or_

    text = lambda key: func.coalesce(model.detail.op("->>")(key), "")
    failed = and_(
        model.category.in_(IMPORT_CATEGORIES), model.action.in_(IMPORT_RESULT_ACTIONS),
        model.status.in_(HANDLED_STATUSES),
        or_(text("business_outcome") == "failed",
            func.coalesce(model.summary, "").contains(EXTRACT_FAILURE_TEXT)),
    )
    duplicate = and_(
        model.category.in_(IMPORT_CATEGORIES), model.action.in_(IMPORT_RESULT_ACTIONS),
        model.status.in_(HANDLED_STATUSES), text("conflict_resolution_action") == "",
        or_(text("business_outcome") == "duplicate", text("source_mode").in_(DUPLICATE_MODES),
            *(func.coalesce(model.summary, "").contains(word) for word in DUPLICATE_TEXTS)),
    )
    return case((failed, "failed"), (duplicate, "success"), else_=model.status)


def annotate_outcome(row):
    """追加展示契约，不篡改原始审计状态。"""
    detail = row.get("detail") or {}
    status = import_result_status(row)
    duplicate = is_duplicate_result(row)
    subtitle = (row.get("category") in {"subtitle_import", "subtitle_pair"}
                or row.get("relation") in {"subtitle_import", "pair"}
                or str(detail.get("source_mode") or "").startswith("linked_translation_archive")
                or detail.get("source_mode") == "subtitle_folder_import")
    if str(detail.get("conflict_resolution_action") or "").upper() == "SKIP":
        outcome, label = "cancelled", "已跳过"
    elif duplicate:
        outcome, label = "duplicate", "重复已跳过" if str(detail.get("source_mode") or "").endswith("_skipped") else "重复待处理"
    elif is_subtitle_handoff(row):
        outcome, label = "pending", "待字幕补配"
    elif status in {"failed", "error"}:
        outcome, label = "failed", "失败"
    elif status == "partial_success":
        outcome, label = "partial", "部分成功"
    elif status in {"cancelled", "aborted"}:
        outcome, label = "cancelled", "已取消"
    elif status in {"success", "completed"}:
        outcome, label = "success", {
            "auto_import": "解压入库成功", "extract": "解压成功", "process_existing": "目录处理成功",
        }.get(row.get("category"), "成功")
    else:
        outcome, label = "pending", "待处理"
    if detail.get("mode") == "conflict_retry_item" and not is_subtitle_handoff(row):
        label = {
            "success": "重试成功", "failed": "重试失败", "partial": "部分重试成功",
            "pending": "重试中", "cancelled": "已取消",
        }.get(outcome, label)
    if row.get("category") in IMPORT_CATEGORIES and row.get("action") in IMPORT_RESULT_ACTIONS:
        row.update(result_status=status, outcome=outcome, outcome_label=label)
    return outcome, subtitle


def project_related_events(row):
    """一次遍历生成筛选计数和节点路径；不复制节点及其大体积文件树。"""
    annotate_outcome(row)
    groups = {key: {"key": key, "label": label, "paths": []} for key, label in (
        ("all", "全部"), ("success", "成功"), ("failed", "失败"),
        ("partial", "部分成功"), ("duplicate", "重复"), ("subtitle", "字幕补配"),
        ("pending", "待处理"), ("cancelled", "已取消"),
    )}
    seen = {str(row["id"])} if row.get("id") else set()

    def walk(node, path):
        for prefix, children in ((["detail", "child_rows"], (node.get("detail") or {}).get("child_rows")),
                                 (["child_rows"], node.get("child_rows"))):
            for index, child in enumerate(children or []):
                if not isinstance(child, dict):
                    continue
                key = str(child.get("id") or (path + prefix + [index]))
                if key in seen:
                    continue
                seen.add(key)
                child_path = path + prefix + [index]
                outcome, subtitle = annotate_outcome(child)
                groups["all"]["paths"].append(child_path)
                groups[outcome]["paths"].append(child_path)
                if subtitle:
                    groups["subtitle"]["paths"].append(child_path)
                walk(child, child_path)

    walk(row, [])
    row.setdefault("detail", {})["related_event_groups"] = [
        {**group, "count": len(group["paths"])} for group in groups.values()
        if group["paths"] or group["key"] == "all"
    ]
    return row
