"""操作记录列表 lite 模式辅助。

设计目标
========
- 默认列表接口要把最多 5000 行 ``activity_logs`` 拉回来跑 1700+ 行的合并算法，
  其中大头是 ``detail`` JSON 反序列化（单条最高 660KB）。即便加了多层缓存，
  首次进入页面 / 高频写入场景仍然会拉到几 MB JSON 慢得人发指。
- "lite" 模式不再做合并、不再回前端整段 detail，只挑出每条记录前端展示需要的
  少量字段：摘要、状态、时间、RJ、source_path，以及从 detail 里提取出的 1~4 个
  关键 metric chip（如 "成功 12 / 失败 3"、"耗时 1m20s"、"3.2 GB"）。
- 这样列表请求体可以从 ~5MB 压到 ~150KB，TTFB 也跟着下来。详细业务面板还是走
  /children 或后续可加的 /detail 接口走完整 detail，只在用户真正点开时才付费。

只在 lite 列表里使用，不要影响任何现有合并逻辑。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .activity_log_service import CATEGORY_LABELS
from .http_download_service import http_download_platforms_from_metadata, http_download_platforms_label

__all__ = [
    "build_lite_item",
    "extract_metric_chips",
    "format_bytes_short",
    "format_duration_short",
]


# ---- 公共格式化 ----
def format_bytes_short(size: Any) -> str:
    try:
        value = float(size or 0)
    except Exception:
        value = 0.0
    if value <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"


def format_duration_short(duration_ms: Any) -> str:
    try:
        total_seconds = max(0, int(round(float(duration_ms or 0) / 1000)))
    except Exception:
        return ""
    if total_seconds <= 0:
        return ""
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds}s" if seconds else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes}m" if minutes else f"{hours}h"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _chip(label: str, value: str, tone: str = "neutral") -> Dict[str, str]:
    """构造单个 metric chip。tone 用于前端选色，常用：success/warn/danger/info/neutral。"""
    return {"label": label, "value": value, "tone": tone}


# ---- 各 category 的 chip 提取 ----
def _chips_for_subtitle_crawl(action: str, status: str, detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    if action == "batch_start":
        created = _int(detail.get("created_count"))
        skipped = _int(detail.get("skipped_total"))
        if created:
            chips.append(_chip("创建", str(created), "info"))
        if skipped:
            chips.append(_chip("跳过", str(skipped), "neutral"))
        return chips
    downloaded = _int(detail.get("downloaded_count"))
    written = _int(detail.get("written_files_count"))
    if downloaded:
        chips.append(_chip("下载", str(downloaded), "info"))
    if written and written != downloaded:
        chips.append(_chip("写入", str(written), "info"))
    if detail.get("awaiting_manual_match"):
        chips.append(_chip("待配对", "·", "warn"))
    return chips


def _chips_for_subtitle_pair(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    pairs = (
        _int(detail.get("applied_pairs"))
        or _int(detail.get("manual_match_applied_pairs"))
        or _int(detail.get("matched_group_count"))
        or _int(detail.get("final_file_count"))
    )
    deleted = _int(detail.get("deleted_subtitles"))
    if pairs:
        chips.append(_chip("配对", str(pairs), "info"))
    if deleted:
        chips.append(_chip("清理", str(deleted), "neutral"))
    return chips


def _chips_for_subtitle_import(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    written = _int(detail.get("final_file_count"))
    if written:
        chips.append(_chip("写入", str(written), "info"))
    return chips


def _chips_for_extract_like(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    arch = format_bytes_short(detail.get("archive_size_bytes"))
    out = format_bytes_short(detail.get("extract_output_bytes") or detail.get("output_size_bytes"))
    dur = format_duration_short(detail.get("duration_ms"))
    if arch:
        chips.append(_chip("压缩包", arch, "neutral"))
    if out:
        chips.append(_chip("产物", out, "info"))
    if dur:
        chips.append(_chip("耗时", dur, "neutral"))
    return chips


def _chips_for_pipeline_filter(action: str, detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    if action == "filter_delete_preview":
        cnt = _int(detail.get("selected_count"))
        size = format_bytes_short(detail.get("selected_size"))
        if cnt:
            chips.append(_chip("命中", str(cnt), "warn"))
        if size:
            chips.append(_chip("大小", size, "neutral"))
    elif action == "filter_delete_apply":
        ok = _int(detail.get("success_count"))
        fail = _int(detail.get("failed_count"))
        size = format_bytes_short(detail.get("deleted_bytes"))
        if ok:
            chips.append(_chip("删除", str(ok), "success"))
        if fail:
            chips.append(_chip("失败", str(fail), "danger"))
        if size:
            chips.append(_chip("释放", size, "info"))
    elif action == "filter_delete_preview_retry":
        ok = _int(detail.get("retry_success_count"))
        fail = _int(detail.get("retry_failed_count"))
        if ok:
            chips.append(_chip("补回", str(ok), "success"))
        if fail:
            chips.append(_chip("失败", str(fail), "danger"))
    return chips


def _chips_for_pipeline_rename(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    ok = _int(detail.get("success_count"))
    fail = _int(detail.get("failed_count"))
    if ok or fail:
        if ok:
            chips.append(_chip("成功", str(ok), "success"))
        if fail:
            chips.append(_chip("失败", str(fail), "danger"))
    return chips


def _chips_for_pipeline_delete(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    ok = _int(detail.get("success_count"))
    fail = _int(detail.get("failed_count"))
    if ok:
        chips.append(_chip("成功", str(ok), "success"))
    if fail:
        chips.append(_chip("失败", str(fail), "danger"))
    return chips


def _chips_for_asmr_sync(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    ok = _int(detail.get("success_count"))
    fail = _int(detail.get("failed_count"))
    uploaded = _int(detail.get("uploaded_count"))
    dl_size = format_bytes_short(detail.get("downloaded_bytes"))
    up_size = format_bytes_short(detail.get("uploaded_bytes"))
    dur = format_duration_short(detail.get("duration_ms"))
    if ok:
        chips.append(_chip("成功", str(ok), "success"))
    if fail:
        chips.append(_chip("失败", str(fail), "danger"))
    if uploaded:
        chips.append(_chip("上传", str(uploaded), "info"))
    if up_size:
        chips.append(_chip("上传量", up_size, "info"))
    elif dl_size:
        chips.append(_chip("下载量", dl_size, "neutral"))
    if dur:
        chips.append(_chip("耗时", dur, "neutral"))
    return chips


def _chips_for_upload(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    uploaded = _int(detail.get("uploaded_count"))
    size = format_bytes_short(detail.get("uploaded_bytes"))
    dur = format_duration_short(detail.get("duration_ms"))
    if uploaded:
        chips.append(_chip("文件", str(uploaded), "info"))
    if size:
        chips.append(_chip("大小", size, "info"))
    if dur:
        chips.append(_chip("耗时", dur, "neutral"))
    return chips


def _chips_for_circle_completion(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    circle = str(detail.get("circle_name") or "").strip()
    selected = _int(detail.get("selected_count"))
    refreshed = _int(detail.get("refreshed_count"))
    changed = _int(detail.get("changed_count"))
    if circle:
        # 社团名直接作为最显眼的 chip
        chips.append(_chip("社团", circle[:20], "info"))
    if selected:
        chips.append(_chip("已选", str(selected), "neutral"))
    if refreshed:
        chips.append(_chip("已刷新", str(refreshed), "info"))
    if changed:
        chips.append(_chip("有更新", str(changed), "success"))
    return chips


def _chips_for_email_watcher(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = []
    matched = _int(detail.get("matched_count"))
    new_works = _int(detail.get("new_work_count"))
    if matched:
        chips.append(_chip("命中邮件", str(matched), "info"))
    if new_works:
        chips.append(_chip("新作", str(new_works), "success"))
    return chips


# ---- 入口 ----
def extract_metric_chips(
    category: Optional[str],
    action: Optional[str],
    status: Optional[str],
    detail: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """从 detail 中提取展示用的 metric chip 列表。最多 4 个 chip，剩下的截断。"""
    if not isinstance(detail, dict):
        return []
    cat = (category or "").strip()
    act = (action or "").strip()
    st = (status or "").strip()

    if cat == "subtitle_crawl":
        chips = _chips_for_subtitle_crawl(act, st, detail)
    elif cat == "subtitle_pair":
        chips = _chips_for_subtitle_pair(detail)
    elif cat == "subtitle_import":
        chips = _chips_for_subtitle_import(detail)
    elif cat in {"extract", "auto_import", "process_existing"}:
        chips = _chips_for_extract_like(detail)
    elif cat == "pipeline_filter":
        chips = _chips_for_pipeline_filter(act, detail)
    elif cat == "pipeline_rename":
        chips = _chips_for_pipeline_rename(detail)
    elif cat == "pipeline_delete":
        chips = _chips_for_pipeline_delete(detail)
    elif cat == "asmr_sync":
        chips = _chips_for_asmr_sync(detail)
    elif cat == "upload":
        chips = _chips_for_upload(detail)
    elif cat == "circle_completion":
        chips = _chips_for_circle_completion(detail)
    elif cat == "email_watcher":
        chips = _chips_for_email_watcher(detail)
    else:
        chips = []

    return chips[:4]


def _safe_summary(value: Any, max_len: int = 280) -> str:
    """裁剪超长 summary（删除过滤预审在异常情况会写出 1~2K 的 summary）。"""
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _has_potential_children(detail: Dict[str, Any], action: str = "") -> bool:
    """轻量判断：detail 是否暗示这条记录下面还能拉到子行。

    重要约束：``batch_id`` / ``session_id`` / ``session_key`` 是 **横向分组键**
    （同一轮的所有兄弟动作共享同一 batch_id），**不是父子关系键**。
    早期版本把它们也当成「有子任务」信号，导致邮件监听一轮里 N 条独立的
    「监视新作直入」单条记录都被错标成「有子任务」，用户点开看到的是
    一堆同级兄弟，体验混乱。本方法现在只信 detail 里 **显式** 表明
    「我下面真的有子任务」的字段或 action 名。

    被认可的「显式有子任务」信号（按可靠性排序）：

    1. 显式子计数字段：``child_row_count`` / ``paired_child_count`` /
       ``unpaired_child_count`` / ``created_count`` / ``triggered``
       —— 写日志时由业务代码主动塞入，存在即代表本行是个聚合摘要。
    2. 显式子任务列表：``child_rows`` / ``created_tasks`` / ``rjcodes`` /
       ``items`` 是非空数组 —— 业务把「我下面的子任务清单」直接放在
       detail 里，存在即代表本行是个批量摘要。
    3. action 以 ``batch_`` 开头（``batch_start`` / ``batch_api_rename``
       / ``batch_summary`` 等）—— 明确的批量动作 action 命名约定。
    4. ``detail.mode`` 以 ``_batch`` / ``_summary`` 结尾（如
       ``email_new_release_batch``）—— 邮件监听 / 字幕抓取等用 mode
       字段区分单条 vs 批次的场景。

    完整判断要扫描 batch_id / parent_id / session_key 在表里有没有对应行，
    太重；这里靠 detail 的显式字段命中即返回 True，命中不到就 False。
    /children 接口仍按 batch_id / parent_id / session_key 全策略拉子行，
    极少数误判（detail 没显式字段但又确实是摘要）由 /children 兜底
    （前端点开看到空就提示空）。
    """
    if not isinstance(detail, dict):
        return False

    for key in (
        "child_row_count",
        "paired_child_count",
        "unpaired_child_count",
        "created_count",
        "triggered",
    ):
        try:
            if int(detail.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue

    for key in ("child_rows", "created_tasks", "rjcodes", "items"):
        val = detail.get(key)
        if isinstance(val, list) and len(val) > 0:
            return True

    if isinstance(action, str) and action.startswith("batch_"):
        return True

    mode = str(detail.get("mode") or "")
    if mode.endswith("_batch") or mode.endswith("_summary"):
        return True

    return False


def build_lite_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 ActivityLog row dict 转成 lite 列表 item。

    输出字段（前端 UI 直接渲染）：
    - id / category / category_label / action / status / created_at
    - rjcode / task_id / source_path
    - summary（裁剪过的）
    - chips: List[{label, value, tone}]，已限制为 ≤4 个
    - has_children: 是否可以展开
    - batch_id / session_key / parent_id（前端发 /children 用）
    """
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    category = row.get("category")
    action = row.get("action")
    status = row.get("status")
    item: Dict[str, Any] = {
        "id": row.get("id"),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, category),
        "action": action,
        "status": status,
        "summary": _safe_summary(row.get("summary")),
        "rjcode": row.get("rjcode"),
        "task_id": row.get("task_id"),
        "source_path": row.get("source_path"),
        "created_at": row.get("created_at"),
        "batch_id": row.get("batch_id") or detail.get("batch_id"),
        "session_key": row.get("session_key") or detail.get("session_key") or detail.get("session_id"),
        "parent_id": row.get("parent_id") or detail.get("parent_id"),
        "chips": extract_metric_chips(category, action, status, detail),
        "has_children": _has_potential_children(detail, action),
        # 给"重新爬取/已修复"等业务标记一个直通字段，前端不需要再扫 detail
        "rerun": bool(detail.get("rerun_linked") or detail.get("rerun_count")),
        "compacted": bool(detail.get("__compacted")),
    }

    if category == "http_download":
        platforms = http_download_platforms_from_metadata(detail)
        platform_label = str(detail.get("platform_label") or "").strip() or http_download_platforms_label(platforms)
        item.update({
            "category_label": f"{platform_label} 下载" if platform_label and platform_label != "HTTP" else "HTTP 下载",
            "platforms": platforms,
            "platform_label": platform_label,
            "download_mode": str(detail.get("download_mode") or "").strip(),
            "source_modes": list(detail.get("source_modes") or []),
        })
    elif category == "baidu_netdisk":
        item.update({
            "category_label": "百度网盘下载",
            "platforms": ["baidu_netdisk"],
            "platform_label": "百度网盘",
            "download_mode": "baidu_netdisk",
            "source_modes": ["baidu_netdisk"],
        })

    # 单条重命名行：列表 UI 需要 old_name / new_name 才能渲染"原 / 新"对比块。
    # lite 路径默认不回传 detail，这里只挑必要字段精简下发，避免又把整段 detail JSON
    # 塞回响应里推高 TTFB。批量行（batch_*）保留原 summary 即可，不挂这个字段。
    if (
        category == "pipeline_rename"
        and action not in ("batch_api_rename", "batch_manual_rename")
        and (detail.get("old_name") or detail.get("new_name"))
    ):
        compact_detail: Dict[str, Any] = {}
        old_name = str(detail.get("old_name") or "").strip()
        new_name = str(detail.get("new_name") or "").strip()
        error_text = str(detail.get("error") or "").strip()
        reason_text = str(detail.get("reason") or "").strip()
        if old_name:
            compact_detail["old_name"] = old_name
        if new_name:
            compact_detail["new_name"] = new_name
        if error_text:
            compact_detail["error"] = error_text
        if reason_text:
            compact_detail["reason"] = reason_text
        if compact_detail:
            item["detail"] = compact_detail

    return item
