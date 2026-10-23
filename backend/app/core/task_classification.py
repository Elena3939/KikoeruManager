"""任务业务分类；展示归属不改变引擎能力。"""

CIRCLE_SUBTYPE_LABELS = {
    "circle_index": "社团索引",
    "work_refresh": "作品状态刷新",
    "owned_check": "本地收录核对",
    "bonus_probe": "特典探测",
    "work_download": "作品下载",
}


def circle_task_classification(kind, metadata):
    kind = getattr(kind, "value", kind)
    subtype = {
        "circle_completion_index": "circle_index",
        "circle_completion_refresh_selected": "owned_check" if metadata.get("owned_only") else "work_refresh",
        "circle_completion_bonus_probe": "bonus_probe",
        "circle_completion_download_batch": "work_download",
    }.get(kind, "")
    if kind in {"http_download", "asmr_sync_download"} and (
        metadata.get("source_page") == "circle-completion"
        or metadata.get("task_domain") == "circle_completion"
    ):
        subtype = "work_download"
    return subtype, CIRCLE_SUBTYPE_LABELS.get(subtype, "")
