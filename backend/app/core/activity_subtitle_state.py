"""字幕抓取和配对是同一任务的处理阶段；读模型保留原始审计状态。"""
from datetime import datetime


def apply_pair_state(crawl, pair):
    if not pair:
        return
    detail = dict(crawl.get("detail") or {})
    payload = pair.get("detail") or {}
    completed = pair.get("status") == "success"
    detail.update(
        pair_linked=True, pair_status=pair.get("status"),
        pair_summary=pair.get("summary"), pair_created_at=pair.get("created_at"),
        manual_match_completed=completed,
        awaiting_manual_match=not completed,
        manual_match_applied_pairs=payload.get("applied_pairs", 0),
    )
    crawl.update(detail=detail, merged_pair=True, merged_pair_status=pair.get("status"))
    if completed:
        crawl.setdefault("original_status", crawl.get("status"))
        crawl.update(status="success", summary=pair.get("summary") or "字幕配对完成")


def enrich_subtitle_items(items, db):
    """只查询当前页任务的最新配对摘要，不读取配对文件清单，不逐行查库。"""
    from ..models.database import ActivityLog

    crawls = []
    for index, row in enumerate(items):
        if row.get("category") != "subtitle_crawl" or not row.get("task_id") or row.get("action") == "batch_start":
            continue
        # 行缓存保存审计快照，当前配对状态只写入本次响应。
        item = {**row, "detail": dict(row.get("detail") or {}), "chips": list(row.get("chips") or [])}
        items[index] = item
        crawls.append(item)
    if not crawls:
        return
    rows = db.query(
        ActivityLog.task_id, ActivityLog.status, ActivityLog.summary, ActivityLog.created_at,
        ActivityLog.detail["applied_pairs"].label("applied_pairs"),
    ).filter(
        ActivityLog.category == "subtitle_pair",
        ActivityLog.task_id.in_({row["task_id"] for row in crawls}),
    ).distinct(ActivityLog.task_id).order_by(
        ActivityLog.task_id, ActivityLog.created_at.desc(), ActivityLog.id.desc(),
    ).all()
    pairs = {row.task_id: row for row in rows}
    for crawl in crawls:
        pair = pairs.get(crawl["task_id"])
        started = crawl.get("created_at")
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        if pair is None or (started and pair.created_at < started):
            continue
        apply_pair_state(crawl, dict(status=pair.status, summary=pair.summary,
            created_at=pair.created_at.isoformat(), detail={"applied_pairs": pair.applied_pairs}))
        if pair.status == "success":
            crawl["chips"] = [chip for chip in crawl.get("chips", []) if chip.get("label") != "待配对"]
            crawl["chips"].append({"label": "配对", "value": str(pair.applied_pairs or 0), "tone": "success"})


def sql_subtitle_status(model, fallback):
    """状态筛选使用同一配对结论，避免成功记录仍落入等待分组。"""
    from sqlalchemy import case, select
    from sqlalchemy.orm import aliased
    pair = aliased(model)
    latest = select(pair.status).where(
        pair.category == "subtitle_pair", pair.task_id == model.task_id,
        pair.created_at >= model.created_at,
    ).order_by(pair.created_at.desc(), pair.id.desc()).limit(1).correlate(model).scalar_subquery()
    return case(((model.category == "subtitle_crawl") & (model.action != "batch_start")
                 & (latest == "success"), "success"), else_=fallback)
