"""任务通知 payload 辅助工具。"""
import os
import re
from datetime import datetime
from typing import Any


_DLSITE_RJ_RE = re.compile(r'^RJ(\d{6}|\d{8})$', re.IGNORECASE)


def dlsite_cover_url(rjcode: Any, *, hd: bool = True) -> str:
    """根据 RJ 号拼出 DLsite 公开封面 URL。

    DLsite 图片资源是按 RJ 号规则化命名的：
      - 高清主图：``https://img.dlsite.jp/modpub/images2/work/doujin/{folder}/{rj}_img_main.jpg``
      - 240x240 缩略图：``https://img.dlsite.jp/resize/images2/work/doujin/{folder}/{rj}_img_main_240x240.jpg``
    其中 ``folder`` 是把 RJ 数字部分按 1000 向上取整再补齐位数得到的目录段。
    用于在没有 ``circle_works`` 元数据时给邮件兜底一张可访问的封面。
    """
    normalized = str(rjcode or "").strip().upper()
    match = _DLSITE_RJ_RE.match(normalized)
    if not match:
        return ""
    digits = match.group(1)
    number = int(digits)
    folder_upper = ((number // 1000) + 1) * 1000
    folder = f"RJ{folder_upper:08d}" if len(digits) == 8 else f"RJ{folder_upper:06d}"
    if hd:
        return f"https://img.dlsite.jp/modpub/images2/work/doujin/{folder}/{normalized}_img_main.jpg"
    return f"https://img.dlsite.jp/resize/images2/work/doujin/{folder}/{normalized}_img_main_240x240.jpg"


def upgrade_dlsite_cover_to_hd(url: Any, rjcode: Any = "") -> str:
    """把 DLsite 240x240 缩略图 URL 升级为高清主图 URL。

    `circle_completion_service._normalize_dlsite_cover_url` 默认把所有 DLsite
    封面归一到 240x240 缩略图（界面列表用），但邮件里需要更大尺寸来避免拉伸
    模糊。这里把 ``_img_main_240x240.jpg`` 替换回 ``_img_main.jpg``，并把
    ``/resize/images2/`` 路径改回 ``/modpub/images2/``。如果 URL 不是 DLsite
    标准格式但 ``rjcode`` 提供了，回落到 :func:`dlsite_cover_url` 重新拼。
    """
    text = str(url or "").strip()
    if text:
        if "_img_main_240x240.jpg" in text:
            text = text.replace("_img_main_240x240.jpg", "_img_main.jpg")
        if "/resize/images2/" in text:
            text = text.replace("/resize/images2/", "/modpub/images2/")
        if "_img_sam.jpg" in text:
            text = text.replace("_img_sam.jpg", "_img_main.jpg")
        return text
    return dlsite_cover_url(rjcode) if rjcode else ""


def set_notification_extra(task, **kwargs) -> None:
    """把额外通知数据塞进任务 metadata，供 outbox payload 合并。"""
    if task is None:
        return
    meta = dict(getattr(task, "task_metadata", None) or {})
    extra = dict(meta.get("notification_extra") or {})
    for key, value in kwargs.items():
        if value is not None:
            extra[key] = value
    meta["notification_extra"] = extra
    task.task_metadata = meta


def build_recent_logs(task, *, max_lines: int = 30, level: str = "info") -> list[dict]:
    """从任务 progress_log/current_step 生成邮件日志块数据。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    raw_logs = list(meta.get("progress_log") or [])
    rows: list[dict] = []
    for item in raw_logs[-max_lines:]:
        if isinstance(item, dict):
            text = item.get("message") or item.get("text") or item.get("step") or ""
            rows.append({
                "level": str(item.get("level") or level).lower(),
                "text": str(text),
                "ts": str(item.get("ts") or item.get("time") or ""),
            })
        else:
            rows.append({"level": level, "text": str(item), "ts": ""})

    current_step = str(getattr(task, "current_step", "") or "").strip()
    if current_step and not any(row.get("text") == current_step for row in rows):
        rows.append({
            "level": level,
            "text": current_step,
            "ts": datetime.now().strftime("%H:%M:%S"),
        })
    return rows[-max_lines:]


def build_import_notification_extra(task, *, error: str = "") -> dict[str, Any]:
    """为解压 / 入库任务构造业务块 payload。

    设计：
      - `file_tree_items` 是 filter_service 返回的 `all_items`，包含解压后所有
        文件 + 文件夹（不带 status）。
      - `filtered_items / filtered_files / filtered_dirs` 是被规则过滤掉的子集。
      - 我们把过滤集合转成 path 集，回填到 `all_items` 行的 `status='filtered'`，
        保持「全部展示 + 过滤项划线」一致的视觉与任务详情对齐。
      - 然后用 `_flat_to_tree` 把扁平 path 重建成嵌套目录树，让邮件里的文件树
        有正常的层级缩进，而不是几十行重复完整路径。
    """
    meta = dict(getattr(task, "task_metadata", None) or {})
    output_path = str(getattr(task, "output_path", "") or meta.get("final_output_path") or "").strip()

    raw_items = list(meta.get("file_tree_items") or [])
    filtered_items = list(meta.get("filtered_items") or [])
    filtered_files = list(meta.get("filtered_files") or [])
    filtered_dirs = list(meta.get("filtered_dirs") or [])

    filtered_set = _build_filtered_path_set(filtered_items, filtered_files, filtered_dirs)
    flat_rows = _flatten_all_items(raw_items, filtered_set)

    # raw_items 为空（例如未跑过滤）时退回扫盘补一份
    if not flat_rows and output_path:
        scan_rows = _normalize_file_tree([], output_path)
        for row in scan_rows:
            rel = _norm_rel_path(row.get("path"))
            if not rel:
                continue
            flat_rows.append({
                "rel": rel,
                "size": int(row.get("size") or 0),
                "size_text": row.get("size_text") or "",
                "status": row.get("status") or "kept",
                "is_dir": False,
            })

    # 扁平中带 status 的行 → 嵌套目录树
    file_tree = _flat_to_tree(flat_rows)

    # 只统计真实保留下来的文件
    kept_count = sum(1 for row in flat_rows if not row.get("is_dir") and row.get("status") != "filtered")
    kept_size = sum(int(row.get("size") or 0) for row in flat_rows if not row.get("is_dir") and row.get("status") != "filtered")

    filtered_size_bytes = int(meta.get("filtered_size") or 0)
    if not filtered_size_bytes:
        # 兜底：filter_service 没写 filtered_size 时，从 filtered_items 的 size 累加
        try:
            filtered_size_bytes = sum(
                int((item or {}).get("size") or 0)
                for item in (filtered_items or [])
                if isinstance(item, dict)
            )
        except Exception:
            filtered_size_bytes = 0

    stats = {
        "total_files": kept_count or _count_files_on_disk(output_path),
        "total_size": _format_bytes(kept_size) or (_format_bytes(_sum_size_on_disk(output_path)) if output_path else ""),
        "filtered_count": int(meta.get("filtered_count") or len(filtered_items or filtered_files or filtered_dirs) or 0),
        "filtered_size": _format_bytes(filtered_size_bytes),
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
    }

    # 构建 RJ 作品卡片（含统计信息）
    rjcode = str(
        meta.get("inferred_rjcode") or meta.get("rjcode") or ""
    ).strip().upper()
    work_title = str(
        meta.get("work_title") or meta.get("work_name") or meta.get("title") or rjcode
    ).strip()
    cover_url = str(
        meta.get("cover_url") or meta.get("mainCoverUrl") or meta.get("main_cover_url") or meta.get("image_url") or ""
    ).strip()
    circle_name = str(meta.get("circle_name") or meta.get("maker_name") or "").strip()

    # 尝试从 circle_works 补封面 / 社团名
    if rjcode and not cover_url:
        circle_id = str(meta.get("circle_id") or "").strip()
        work_map = _load_circle_work_map(circle_id, [rjcode])
        row = work_map.get(rjcode) or {}
        cover_url = str(row.get("image_url") or "").strip()
        circle_name = circle_name or str(row.get("maker_name") or "").strip()

    rj_work_cards: list[dict] = []
    card_status = "failed" if error else "success"
    if rjcode or work_title or cover_url:
        # 卡片下方的元信息行：用 lucide SVG 图标 + 文本，与文件树视觉一致
        card_changes: list[dict[str, str]] = []
        if error:
            card_changes.append({"icon": "x-circle", "text": f"处理失败：{error}"})
        if stats["total_files"]:
            total_text = f"{stats['total_files']} 个文件"
            if stats["total_size"]:
                total_text += f" · {stats['total_size']}"
            card_changes.append({"icon": "folder", "text": total_text})
        if stats["filtered_count"]:
            filtered_text = f"已过滤 {stats['filtered_count']} 个文件"
            if stats["filtered_size"]:
                filtered_text += f" · {stats['filtered_size']}"
            card_changes.append({"icon": "filter-x", "text": filtered_text})
        if stats["duration"]:
            card_changes.append({"icon": "clock", "text": f"用时 {stats['duration']}"})
        rj_work_cards.append({
            "rjcode": rjcode,
            "title": work_title or rjcode or "入库作品",
            "cover_url": cover_url,
            "circle_name": circle_name,
            "size_text": stats["total_size"] or "",
            "file_count": stats["total_files"],
            "count_label": f"{stats['total_files']} 个文件" if stats["total_files"] else "",
            "changes": card_changes,
            "status": card_status,
            "error": str(error or ""),
        })

    # 构建日志（追加密码信息）
    recent_logs = build_recent_logs(task, max_lines=30)
    password_used = str(
        meta.get("resolved_password") or meta.get("manual_retry_password") or ""
    ).strip()
    if password_used:
        ts = datetime.now().strftime("%H:%M:%S")
        recent_logs.append({"level": "info", "text": f"🔑 使用密码解压：{password_used}", "ts": ts})

    result: dict[str, Any] = {
        "stats": stats,
        "file_tree": file_tree[:200],
        "recent_logs": recent_logs,
    }
    if rj_work_cards:
        result["rj_work_cards"] = rj_work_cards
    if error:
        result["error_logs"] = [{"level": "error", "text": str(error), "ts": datetime.now().strftime("%H:%M:%S")}]
        result["summary"] = str(error)
    return result


def aggregate_import_batch_extras(primary_task, group_tasks) -> dict[str, Any]:
    """把批量解压 / 入库任务组的业务块合并成一个 payload。

    - 遍历组内每个任务，取 `notification_extra` 里已经构建好的卡片 / 文件树；
      如果任务是 `auto_process / process_existing_folder`，但还没写入 extra
      （例如旧任务），则临时跑一次 `build_import_notification_extra` 作为兜底。
    - 所有 `rj_work_cards` 平铺拼接，成功在前、失败在后。
    - `file_tree` 拼接各任务以 RJ 为根的顶层节点，确保每个 RJ 自成一棵子树。
    - 统计字段累加；`recent_logs` 合并每个失败任务一条摘要。
    """
    cards_success: list[dict] = []
    cards_failed: list[dict] = []
    file_tree_roots: list[dict] = []
    total_files = 0
    filtered_count = 0
    failed_summary_logs: list[dict] = []
    error_logs: list[dict] = []
    all_recent_logs: list[dict] = []

    # 计算批量墙钟耗时所需的时间区间
    earliest_start = None
    latest_end = None

    seen_ids = set()
    ordered_tasks = []
    if primary_task is not None:
        ordered_tasks.append(primary_task)
        seen_ids.add(getattr(primary_task, "id", None))
    for t in group_tasks or []:
        if getattr(t, "id", None) in seen_ids:
            continue
        seen_ids.add(getattr(t, "id", None))
        ordered_tasks.append(t)

    subtitle_manual_by_rj: dict[str, dict[str, Any]] = {}
    for t in ordered_tasks:
        meta = dict(getattr(t, "task_metadata", None) or {})
        task_kind = (t.type.value if hasattr(getattr(t, "type", None), "value") else str(getattr(t, "type", "")))
        if task_kind != "rj_subtitle_fetch":
            continue
        if not bool(meta.get("awaiting_manual_match")) or bool(meta.get("manual_match_completed")):
            continue
        rjcode = str(meta.get("target_rjcode") or meta.get("rjcode") or meta.get("actual_rjcode") or "").strip().upper()
        if not rjcode:
            continue
        downloaded = _safe_int(meta.get("downloaded_count")) or len(meta.get("download_files") or []) or len(meta.get("written_files") or [])
        subtitle_manual_by_rj[rjcode] = {
            "downloaded": downloaded,
            "message": str(getattr(t, "current_step", "") or "等待字幕筛选与配对").strip(),
        }

    for t in ordered_tasks:
        meta = dict(getattr(t, "task_metadata", None) or {})
        task_kind = (t.type.value if hasattr(getattr(t, "type", None), "value") else str(getattr(t, "type", "")))
        if task_kind not in {"auto_process", "process_existing_folder", "extract"}:
            continue
        extra = dict(meta.get("notification_extra") or {})
        if not extra:
            if task_kind in {"auto_process", "process_existing_folder", "extract"}:
                extra = build_import_notification_extra(t, error=str(getattr(t, "error_message", "") or ""))
            else:
                continue

        cards = list(extra.get("rj_work_cards") or [])
        tree_roots = list(extra.get("file_tree") or [])
        stats = dict(extra.get("stats") or {})
        task_logs = list(extra.get("recent_logs") or [])

        try:
            total_files += int(stats.get("total_files") or 0)
        except Exception:
            pass
        try:
            filtered_count += int(stats.get("filtered_count") or 0)
        except Exception:
            pass

        # 累积起止时间计算整体耗时
        started_at = getattr(t, "started_at", None)
        completed_at = getattr(t, "completed_at", None)
        if started_at is not None and (earliest_start is None or started_at < earliest_start):
            earliest_start = started_at
        if completed_at is not None and (latest_end is None or completed_at > latest_end):
            latest_end = completed_at

        task_error = str(getattr(t, "error_message", "") or "")
        card_label = ""
        for card in cards:
            if not isinstance(card, dict):
                continue
            status = str(card.get("status") or ("failed" if task_error else "success"))
            if status == "failed" and not card.get("error") and task_error:
                card = {**card, "error": task_error, "status": "failed"}
            card_rjcode = str(card.get("rjcode") or "").strip().upper()
            manual_info = subtitle_manual_by_rj.get(card_rjcode)
            if manual_info and status != "failed":
                changes = list(card.get("changes") or [])
                downloaded = int(manual_info.get("downloaded") or 0)
                subtitle_text = "待字幕补配"
                if downloaded:
                    subtitle_text += f"：已导入原始字幕 {downloaded} 个，等待人工配对"
                else:
                    subtitle_text += "：等待人工配对"
                changes.append({"icon": "link", "text": subtitle_text})
                card = {
                    **card,
                    "status": "warning",
                    "subtitle_status": "waiting_manual",
                    "subtitle_status_label": "待字幕补配",
                    "changes": changes,
                }
                status = "warning"
            if not card_label:
                card_label = str(card.get("rjcode") or card.get("title") or "").strip()
            (cards_failed if status == "failed" else cards_success).append(card)

        for root in tree_roots:
            if isinstance(root, dict):
                file_tree_roots.append(root)

        # 归并该任务的日志并加上 RJ 前缀，方便在批量大日志中定位
        prefix_label = card_label or str(getattr(t, "name", "") or getattr(t, "id", ""))[:16]
        for entry in task_logs:
            if isinstance(entry, dict):
                text = str(entry.get("text") or "").strip()
                if not text:
                    continue
                all_recent_logs.append({
                    "level": str(entry.get("level") or "info"),
                    "text": f"[{prefix_label}] {text}" if prefix_label else text,
                    "ts": str(entry.get("ts") or ""),
                })
            else:
                text = str(entry or "").strip()
                if text:
                    all_recent_logs.append({
                        "level": "info",
                        "text": f"[{prefix_label}] {text}" if prefix_label else text,
                        "ts": "",
                    })

        if task_error:
            label = prefix_label or "任务"
            failed_summary_logs.append({
                "level": "error",
                "text": f"{label}：{task_error}",
                "ts": datetime.now().strftime("%H:%M:%S"),
            })
            error_logs.append({
                "level": "error",
                "text": f"{label}：{task_error}",
                "ts": datetime.now().strftime("%H:%M:%S"),
            })

    merged_cards = cards_success + cards_failed
    recent_logs = all_recent_logs + failed_summary_logs

    total_duration = _format_duration(earliest_start, latest_end) if earliest_start and latest_end else ""

    stats_out = {
        "total_files": total_files,
        "total_size": "",
        "filtered_count": filtered_count,
        "success_count": len(cards_success),
        "failed_count": len(cards_failed),
        "duration": total_duration,
        "total_duration": total_duration,
    }

    result: dict[str, Any] = {
        "stats": stats_out,
        "recent_logs": recent_logs,
    }
    if merged_cards:
        result["rj_work_cards"] = merged_cards
    if file_tree_roots:
        result["file_tree"] = file_tree_roots[:200]
    if error_logs:
        result["error_logs"] = error_logs
    return result


def build_notification_extra_for_task(task) -> dict[str, Any]:
    """从任务详情 metadata 自动抽取邮件业务组件数据。

    路由优先级说明：
      `task_metadata.task_domain` 在「从社团补全页触发下载」之类的场景会被强行
      置为 `circle_completion`（用于任务中心分组），但任务真实 `kind` 仍是
      `asmr_sync_download`。所以这里**优先按 kind（任务真实类型）路由**，
      只有 kind 没有命中时才回退到 domain。否则一切走社团补全的下载都会被
      错误地塞进「社团索引概览」邮件里。
    """
    meta = dict(getattr(task, "task_metadata", None) or {})
    domain = str(meta.get("task_domain") or "").strip()
    kind = str(meta.get("task_kind") or getattr(getattr(task, "type", None), "value", "") or "").strip()

    # ─── 第一优先：按真实 task kind 路由 ───
    if kind in {"asmr_sync_download", "baidu_netdisk_download", "http_download"}:
        title = "百度网盘文件" if kind == "baidu_netdisk_download" else "下载文件"
        return build_download_notification_extra(task, title=title)
    if kind == "local_library_upload":
        return build_upload_notification_extra(task)
    if kind == "baidu_netdisk_upload":
        return build_upload_notification_extra(task)
    if kind == "rj_subtitle_fetch":
        return build_subtitle_notification_extra(task)
    # 仅这两种是真正的「社团补全索引 / 状态刷新」任务，会跑 36 行作品概览
    if kind == "circle_completion_refresh_selected":
        return build_circle_refresh_selected_notification_extra(task)
    if kind == "circle_completion_index":
        return build_circle_completion_notification_extra(task)
    # circle_completion_download_batch 是个空壳控制任务，不需要业务块，落到默认分支

    # ─── 兜底：按 domain 路由（kind 未识别时） ───
    if domain == "upload":
        return build_upload_notification_extra(task)
    if domain in {"asmr_sync", "http_download", "baidu_netdisk"}:
        title = "百度网盘文件" if domain == "baidu_netdisk" else "下载文件"
        return build_download_notification_extra(task, title=title)
    if domain == "rj_subtitle":
        return build_subtitle_notification_extra(task)
    if domain == "circle_completion":
        # 走到这里说明 kind 没明确归类（既不是 index 也不是 download / batch），
        # 才退回社团概览
        return build_circle_completion_notification_extra(task)

    if any(meta.get(key) for key in ("file_tree_items", "filtered_items", "filtered_files", "filtered_dirs")):
        return build_import_notification_extra(task, error=str(getattr(task, "error_message", "") or ""))

    # ─── 问题作品 / 重复作品（waiting_manual 且非字幕补配） ───
    task_status_val = str(
        getattr(getattr(task, "status", None), "value", "")
        or getattr(task, "status", "")
        or ""
    ).strip().lower()
    if task_status_val == "waiting_manual" and not meta.get("awaiting_manual_match"):
        return build_problem_work_notification_extra(task)

    result: dict[str, Any] = {}
    logs = build_recent_logs(task, max_lines=30)
    if logs:
        result["recent_logs"] = logs
    return result


def build_problem_work_notification_extra(task) -> dict[str, Any]:
    """为重复作品 / 等待人工处理问题作品构造邮件卡片。

    适用场景：task.status == WAITING_MANUAL 且不是字幕补配任务。
    根据 current_step 内容区分「重复作品（duplicate）」和
    「其他需人工处理（waiting_manual）」两种卡片样式。
    """
    meta = dict(getattr(task, "task_metadata", None) or {})
    rjcode = str(
        meta.get("inferred_rjcode") or meta.get("rjcode") or ""
    ).strip().upper()
    work_title = str(
        meta.get("work_title") or meta.get("work_name") or meta.get("title") or rjcode
    ).strip()
    cover_url = str(
        meta.get("cover_url") or meta.get("mainCoverUrl") or meta.get("main_cover_url") or meta.get("image_url") or ""
    ).strip()
    circle_name = str(meta.get("circle_name") or meta.get("maker_name") or "").strip()

    # 尝试从 circle_works 补封面 / 社团名
    if rjcode and not cover_url:
        try:
            circle_id = str(meta.get("circle_id") or "").strip()
            work_map = _load_circle_work_map(circle_id, [rjcode])
            row = work_map.get(rjcode) or {}
            cover_url = str(row.get("image_url") or "").strip()
            circle_name = circle_name or str(row.get("maker_name") or "").strip()
        except Exception:
            pass

    current_step = str(getattr(task, "current_step", "") or "").strip()
    is_duplicate = "重复" in current_step or bool(meta.get("is_duplicate"))

    if is_duplicate:
        card_status = "duplicate"
        reason_text = "检测到重复作品，请在问题作品页面处理"
        changes = [
            {"icon": "copy", "text": reason_text},
        ]
        # 如果有已存在路径信息，补充一行
        existing_path = str(meta.get("existing_path") or meta.get("conflict_path") or "").strip()
        if existing_path:
            import os as _os
            changes.append({"icon": "folder", "text": f"已存在：{_os.path.basename(existing_path)}"})
    else:
        card_status = "waiting_manual"
        reason_text = str(getattr(task, "error_message", "") or current_step or "需要人工处理").strip()
        changes = [
            {"icon": "alert-triangle", "text": reason_text or "需要人工处理"},
        ]

    card = {
        "rjcode": rjcode,
        "title": work_title or rjcode or "问题作品",
        "cover_url": cover_url,
        "circle_name": circle_name,
        "size_text": "",
        "file_count": 0,
        "count_label": "",
        "changes": changes,
        "status": card_status,
        "error": "",
    }
    recent_logs = build_recent_logs(task, max_lines=20)
    result: dict[str, Any] = {
        "rj_work_cards": [card],
    }
    if recent_logs:
        result["recent_logs"] = recent_logs
    return result


def build_circle_completion_notification_extra(task) -> dict[str, Any]:
    """社团补全：统计 + 类似详情页的来源概括表 + 执行日志。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    batch_rows = _normalize_circle_batch_rows(meta.get("batch_circle_summaries") or meta.get("index_batch_results") or [])
    if batch_rows:
        success_rows = [row for row in batch_rows if row.get("success", True)]
        failed_rows = [row for row in batch_rows if not row.get("success", True)]
        works = sum(_safe_int(row.get("works")) for row in success_rows)
        missing = sum(_safe_int(row.get("missing_count")) for row in success_rows)
        stats = {
            "circle_count": len(batch_rows),
            "completed_circles": len(success_rows),
            "failed_circles": len(failed_rows),
            "works": works,
            "local_owned": sum(_safe_int(row.get("local_owned_count")) for row in success_rows),
            "owned": sum(_safe_int(row.get("kikoeru_owned_count")) for row in success_rows),
            "dl_count": sum(_safe_int(row.get("dl_count")) for row in success_rows),
            "asmr_one": sum(_safe_int(row.get("asmr_available_count")) for row in success_rows),
            "downloadable": sum(_safe_int(row.get("downloadable_count")) for row in success_rows),
            "missing": missing,
            "search_efficiency": _format_circle_search_efficiency(works, missing),
            "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        }
        summary = f"批量补全 {len(batch_rows)} 个社团，成功 {len(success_rows)} 个"
        if failed_rows:
            summary += f"，失败 {len(failed_rows)} 个"
        return {
            "stats": stats,
            "summary": summary,
            "circle_batch_summary": batch_rows,
            "recent_logs": build_recent_logs(task, max_lines=30),
        }

    counts = dict(meta.get("indexed_counts") or {})
    result_payload = dict(meta.get("index_result") or {})
    summary = dict(result_payload.get("summary") or {})
    if summary:
        counts = {**summary, **counts}

    circle_id = str(meta.get("circle_id") or result_payload.get("circle_id") or "").strip()
    circle_name = str(meta.get("circle_name") or summary.get("circle_name") or meta.get("circle_query") or "").strip()

    rows = _load_circle_overview_rows(circle_id, limit=36)
    local_owned = _safe_int(counts.get("local_owned_count"))
    owned = _safe_int(counts.get("owned_count"))
    dl_count = _safe_int(counts.get("dl_count"))
    downloadable = _safe_int(counts.get("downloadable_count"))
    missing = _safe_int(counts.get("missing_count"))
    works = _safe_int(counts.get("works")) or len(rows)
    asmr_one = sum(1 for row in rows if row.get("asmr_one") and row.get("asmr_one") != "暂无来源")
    dl_only = sum(1 for row in rows if row.get("kikoeru") == "未收录" and row.get("dlsite") != "暂无来源" and row.get("asmr_one") == "暂无来源")

    stats = {
        "works": works,
        "local_owned": local_owned,
        "owned": owned,
        "dl_count": dl_count,
        "asmr_one": asmr_one,
        "downloadable": downloadable,
        "missing": missing,
        "search_efficiency": _format_circle_search_efficiency(works, missing),
        "dl_only": dl_only,
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
    }
    diff_items = [
        {"label": "本地", "old": "", "new": f"{local_owned} 个"},
        {"label": "Kikoeru", "old": "", "new": f"{owned} 个"},
        {"label": "DLsite", "old": "", "new": f"{dl_count} 个"},
        {"label": "asmr.one", "old": "", "new": f"{asmr_one} 个"},
        {"label": "可下载", "old": "", "new": f"{downloadable} 个"},
        {"label": "暂无来源", "old": "", "new": f"{dl_only} 个"},
    ]
    extra: dict[str, Any] = {
        "stats": stats,
        "circle_name": circle_name,
        "circle_id": circle_id,
        "circle_overview": rows,
        "circle_diff": diff_items,
        "recent_logs": build_recent_logs(task, max_lines=30),
    }
    if circle_name:
        extra["summary"] = (
            f"{circle_name}：共 {works} 个作品，DLsite {dl_count} 个，"
            f"asmr.one {asmr_one} 个，可下载 {downloadable} 个，暂无来源 {dl_only} 个"
        )
    return extra


def _normalize_circle_batch_rows(raw_rows: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        source = raw
        if isinstance(raw.get("result"), dict):
            result = raw.get("result") or {}
            source = {
                **raw,
                **dict(result.get("indexed_counts") or {}),
                "circle_id": result.get("circle_id") or raw.get("circle_id"),
                "circle_name": ((result.get("summary") or {}).get("circle_name") if isinstance(result.get("summary"), dict) else "") or raw.get("circle_name") or raw.get("circle_query"),
            }
        rows.append({
            "success": bool(source.get("success", True)),
            "circle_query": str(source.get("circle_query") or "").strip(),
            "circle_id": str(source.get("circle_id") or "").strip(),
            "circle_name": str(source.get("circle_name") or source.get("circle_query") or "").strip(),
            "works": _safe_int(source.get("works")),
            "local_owned_count": _safe_int(source.get("local_owned_count")),
            "kikoeru_owned_count": _safe_int(source.get("kikoeru_owned_count") or source.get("owned_count")),
            "dl_count": _safe_int(source.get("dl_count")),
            "asmr_available_count": _safe_int(source.get("asmr_available_count") or source.get("downloadable_count")),
            "downloadable_count": _safe_int(source.get("downloadable_count")),
            "missing_count": _safe_int(source.get("missing_count")),
            "error_message": str(source.get("error_message") or "").strip(),
        })
    return rows


def build_circle_refresh_selected_notification_extra(task) -> dict[str, Any]:
    """社团补全手动刷新：只展示本次选中的作品变化。"""
    meta = dict(getattr(task, "task_metadata", None) or {})
    result = dict(meta.get("refresh_result") or {})
    circle_id = str(result.get("circle_id") or meta.get("circle_id") or "").strip()
    circle_name = str(result.get("circle_name") or meta.get("circle_name") or "").strip()
    items = list(result.get("items") or [])
    selected_count = _safe_int(result.get("selected_count")) or _safe_int(meta.get("selected_count")) or len(items)
    refreshed_count = _safe_int(result.get("refreshed_count")) or len(items)
    changed_count = _safe_int(result.get("changed_count")) or sum(1 for item in items if isinstance(item, dict) and item.get("changed"))
    cards = _build_circle_refresh_cards(circle_id, items)

    stats = {
        "total_files": refreshed_count,
        "total_size": f"有更新 {changed_count} 个",
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        "selected_count": selected_count,
        "refreshed_count": refreshed_count,
        "changed_count": changed_count,
    }
    diff_items = [
        {"label": "已选", "old": "", "new": f"{selected_count} 个"},
        {"label": "已刷新", "old": "", "new": f"{refreshed_count} 个"},
        {"label": "有更新", "old": "", "new": f"{changed_count} 个"},
    ]
    summary = f"{circle_name or circle_id}：本次刷新 {refreshed_count} 个作品，{changed_count} 个有更新"
    return {
        "stats": stats,
        "summary": summary,
        "circle_name": circle_name,
        "circle_id": circle_id,
        "circle_diff": diff_items,
        "rj_work_cards": cards[:50],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }


def build_upload_notification_extra(task) -> dict[str, Any]:
    meta = dict(getattr(task, "task_metadata", None) or {})
    upload_items = list(meta.get("upload_files") or [])
    uploaded_items = list(meta.get("uploaded_files") or [])
    base_items = upload_items or uploaded_items
    uploaded_set = _build_uploaded_path_set(uploaded_items)

    flat_rows = _items_to_flat_rows(base_items, uploaded_set, default_status="pending" if upload_items else "completed")
    file_tree = _flat_to_tree(flat_rows)

    runtime = dict(meta.get("upload_runtime") or {})
    total_bytes = _safe_int(runtime.get("total_bytes")) or sum(int(r.get("size") or 0) for r in flat_rows if not r.get("is_dir"))
    completed_files = _safe_int(runtime.get("completed_files")) or len(uploaded_items)
    file_count = sum(1 for r in flat_rows if not r.get("is_dir")) or completed_files
    stats = {
        "total_files": file_count,
        "uploaded_count": completed_files,
        "total_size": _format_bytes(total_bytes),
        "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
    }

    # 构建 RJ 作品卡片
    rjcode = str(meta.get("inferred_rjcode") or meta.get("rjcode") or getattr(task, "rjcode", "") or "").strip().upper()
    work_title = str(meta.get("work_title") or meta.get("work_name") or meta.get("title") or meta.get("source_label") or rjcode).strip()
    cover_url = str(meta.get("cover_url") or meta.get("mainCoverUrl") or meta.get("main_cover_url") or "").strip()
    circle_name = str(meta.get("circle_name") or "").strip()
    if not cover_url and rjcode:
        circle_id = str(meta.get("circle_id") or "").strip()
        work_map = _load_circle_work_map(circle_id, [rjcode])
        row = work_map.get(rjcode) or {}
        cover_url = cover_url or str(row.get("image_url") or "").strip()
        circle_name = circle_name or str(row.get("maker_name") or "").strip()
    rj_work_cards: list[dict] = []
    if rjcode or work_title or cover_url:
        card_changes = [
            {"icon": "file-text", "text": f"文件数 {file_count} 个"},
            {"icon": "folder", "text": f"大小 {_format_bytes(total_bytes)}"},
            {"icon": "clock", "text": f"用时 {stats['duration'] or '-'}"},
            {"icon": "check-circle", "text": f"已上传 {completed_files} 个"},
        ]
        rj_work_cards.append({
            "rjcode": rjcode, "title": work_title, "cover_url": cover_url,
            "circle_name": circle_name, "size_text": _format_bytes(total_bytes),
            "file_count": file_count, "count_label": f"{_format_bytes(total_bytes)} / {file_count} 个",
            "changes": card_changes,
        })

    result = {
        "stats": stats,
        "file_tree": file_tree,
        "recent_logs": build_recent_logs(task, max_lines=30),
    }
    if rj_work_cards:
        result["rj_work_cards"] = rj_work_cards
    return result


def build_download_notification_extra(task, *, title: str = "下载文件") -> dict[str, Any]:
    """下载邮件 payload。

    设计与任务详情页的「文件清单」对齐：
      - 把扁平 `download_files` 按相对路径重建成嵌套目录树（与解压链路一致）。
      - 如果任务带了 `uploaded_files`，把命中的叶子打上 `已上传` badge，
        在邮件里直接显示对应的标签（与活动详情页一致）。
    """
    meta = dict(getattr(task, "task_metadata", None) or {})
    download_items = list(meta.get("download_files") or [])
    uploaded_items = list(meta.get("uploaded_files") or [])
    failed_items = list(meta.get("failed_files") or [])

    uploaded_set = _build_uploaded_path_set(uploaded_items)
    failed_set = _build_uploaded_path_set(failed_items)
    flat_rows = _items_to_flat_rows(download_items, uploaded_set, failed_set=failed_set, default_status="kept")
    file_tree = _flat_to_tree(flat_rows)
    total_bytes = sum(int(r.get("size") or 0) for r in flat_rows if not r.get("is_dir"))
    work_cards = _build_download_work_cards(task, meta, flat_rows)
    completed_count = sum(
        1 for item in download_items
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "completed"
    )
    failed_logs = []
    for item in failed_items[:20]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("relative_path") or item.get("name") or item.get("filename") or "未命名文件").strip()
        reason = str(item.get("failure_reason") or item.get("reason") or "下载失败").strip()
        failed_logs.append({
            "level": "error",
            "text": f"{name}: {reason}" if name else reason,
            "ts": "",
        })
    retry_count = _safe_int(meta.get("auto_retry_attempts") or meta.get("retry_count"))
    recent_logs = build_recent_logs(task, max_lines=40)
    if retry_count and failed_items:
        recent_logs.append({
            "level": "warning",
            "text": f"已自动重试 {retry_count} 轮，仍有 {len(failed_items)} 个文件失败",
            "ts": "",
        })

    result = {
        "stats": {
            "total_files": sum(1 for r in flat_rows if not r.get("is_dir")) or _safe_int(meta.get("selected_resource_count")),
            "downloaded": completed_count,
            "success_count": completed_count,
            "failed_count": len(failed_items),
            "uploaded_count": sum(1 for r in flat_rows if not r.get("is_dir") and "已上传" in (r.get("badges") or [])),
            "total_size": _format_bytes(total_bytes),
            "duration": _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None)),
        },
        "file_tree": file_tree[:200],
        "download_files": file_tree[:200],
        "rj_work_cards": work_cards[:24],
        "download_work_cards": work_cards[:24],
        "recent_logs": recent_logs,
    }
    if failed_logs:
        result["error_logs"] = failed_logs
    return result


def _build_download_work_cards(task, meta: dict, flat_rows: list[dict]) -> list[dict]:
    """为下载完成邮件生成作品卡片：封面、标题、RJ、大小。"""
    selected_resources = list(meta.get("selected_resources") or [])
    rjcode = str(meta.get("rjcode") or getattr(task, "rjcode", "") or "").strip().upper()
    title = str(
        meta.get("work_title")
        or meta.get("work_name")
        or meta.get("title")
        or meta.get("source_label")
        or rjcode
    ).strip()
    cover_url = str(
        meta.get("cover_url")
        or meta.get("mainCoverUrl")
        or meta.get("main_cover_url")
        or meta.get("image_url")
        or ""
    ).strip()
    circle_name = str(meta.get("circle_name") or "").strip()
    if not cover_url:
        circle_id = str(meta.get("circle_id") or "").strip()
        canonical = str(meta.get("canonical_rjcode") or rjcode).strip().upper()
        work_map = _load_circle_work_map(circle_id, [canonical, rjcode])
        row = work_map.get(canonical) or work_map.get(rjcode) or {}
        cover_url = str(row.get("image_url") or "").strip()
        circle_name = circle_name or str(row.get("maker_name") or "").strip()

    resource_bytes = 0
    for item in selected_resources:
        if not isinstance(item, dict):
            continue
        resource_bytes += _safe_int(item.get("size") or item.get("size_bytes") or item.get("file_size"))
        cover_url = cover_url or str(item.get("cover_url") or item.get("image_url") or item.get("mainCoverUrl") or "").strip()
    total_bytes = sum(int(row.get("size") or 0) for row in flat_rows if not row.get("is_dir")) or resource_bytes
    file_count = sum(1 for row in flat_rows if not row.get("is_dir")) or _safe_int(meta.get("selected_resource_count")) or len(selected_resources)

    if not any([rjcode, title, cover_url, total_bytes, file_count]):
        return []
    duration = _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None))
    changes: list[dict[str, str]] = [{"icon": "check-circle", "text": "下载完成"}]
    if file_count:
        total_text = f"{file_count} 个文件"
        if total_bytes:
            total_text += f" · {_format_bytes(total_bytes)}"
        changes.append({"icon": "folder", "text": total_text})
    if duration:
        changes.append({"icon": "clock", "text": f"用时 {duration}"})
    return [{
        "rjcode": rjcode,
        "title": title or rjcode or "下载作品",
        "cover_url": cover_url,
        "circle_name": circle_name,
        "size_text": _format_bytes(total_bytes),
        "file_count": file_count,
        "count_label": f"{file_count} 个文件" if file_count else "",
        "changes": changes,
        "status": "success",
    }]


def build_subtitle_notification_extra(task) -> dict[str, Any]:
    meta = dict(getattr(task, "task_metadata", None) or {})
    downloaded = [_normalize_tree_item(item, status="new") for item in list(meta.get("download_files") or []) if item]
    written = [_normalize_tree_item(item, status="kept") for item in list(meta.get("written_files") or []) if item]
    skipped = [_normalize_tree_item(item, status="filtered") for item in list(meta.get("skipped_files") or []) if item]
    rows = [row for row in [*downloaded, *written, *skipped] if row]
    downloaded_count = _safe_int(meta.get("downloaded_count")) or len(downloaded)
    existing_count = _safe_int(meta.get("existing_subtitle_count"))
    duration = _format_duration(getattr(task, "started_at", None), getattr(task, "completed_at", None))
    rjcode = str(meta.get("target_rjcode") or meta.get("rjcode") or meta.get("actual_rjcode") or getattr(task, "rjcode", "") or "").strip().upper()
    title = str(meta.get("work_title") or meta.get("work_name") or meta.get("title") or meta.get("folder_name") or rjcode).strip()
    cover_url = str(meta.get("cover_url") or meta.get("mainCoverUrl") or meta.get("main_cover_url") or meta.get("image_url") or "").strip()
    circle_name = str(meta.get("circle_name") or meta.get("maker_name") or "").strip()
    if rjcode and (not cover_url or not circle_name):
        circle_id = str(meta.get("circle_id") or "").strip()
        work_map = _load_circle_work_map(circle_id, [rjcode])
        row = work_map.get(rjcode) or {}
        cover_url = cover_url or str(row.get("image_url") or "").strip()
        circle_name = circle_name or str(row.get("maker_name") or "").strip()
        title = title or str(row.get("title") or "").strip()
    awaiting_manual = bool(meta.get("awaiting_manual_match")) and not bool(meta.get("manual_match_completed"))
    changes: list[dict[str, str]] = []
    if awaiting_manual:
        changes.append({"icon": "link", "text": "待字幕补配：等待人工筛选与配对"})
    else:
        changes.append({"icon": "check-circle", "text": "字幕处理完成"})
    if downloaded_count:
        changes.append({"icon": "folder", "text": f"已导入原始字幕 {downloaded_count} 个"})
    if written:
        changes.append({"icon": "file-text", "text": f"已写入字幕 {len(written)} 个"})
    if skipped:
        changes.append({"icon": "filter-x", "text": f"已跳过 {len(skipped)} 个"})
    if existing_count:
        changes.append({"icon": "hard-drive", "text": f"现有字幕 {existing_count} 个"})
    if duration:
        changes.append({"icon": "clock", "text": f"用时 {duration}"})
    rj_work_cards = []
    if rjcode or title or cover_url:
        rj_work_cards.append({
            "rjcode": rjcode,
            "title": title or rjcode or "字幕任务",
            "cover_url": cover_url,
            "circle_name": circle_name,
            "size_text": "待字幕补配" if awaiting_manual else "字幕处理完成",
            "file_count": downloaded_count or len(written) or len(rows),
            "count_label": f"{downloaded_count} 个原始字幕" if downloaded_count else "",
            "changes": changes,
            "status": "warning" if awaiting_manual else "success",
            "subtitle_status": "waiting_manual" if awaiting_manual else "completed",
            "subtitle_status_label": "待字幕补配" if awaiting_manual else "字幕处理完成",
        })
    return {
        "stats": {
            "downloaded": downloaded_count,
            "written": len(written),
            "skipped": len(skipped),
            "existing_subtitles": existing_count,
            "duration": duration,
        },
        "rj_work_cards": rj_work_cards,
        "file_tree": rows[:120],
        "recent_logs": build_recent_logs(task, max_lines=30),
    }


def _load_circle_overview_rows(circle_id: str, *, limit: int = 36) -> list[dict]:
    if not circle_id:
        return []
    try:
        from ..models.database import SessionLocal, CircleWork
        db = SessionLocal()
        try:
            rows = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == circle_id)
                .all()
            )
            rows.sort(key=lambda row: (
                bool(getattr(row, "has_kikoeru", False)),
                not bool(getattr(row, "has_asmr_one", False)),
                str(getattr(row, "display_rjcode", "") or getattr(row, "canonical_rjcode", "") or ""),
            ))
            result = []
            for row in rows[:limit]:
                kikoeru = "已收录" if bool(row.has_kikoeru) else "未收录"
                dlsite = str(row.display_rjcode or row.canonical_rjcode or "").strip() if bool(row.has_dlsite) else "暂无来源"
                asmr_one = str(row.asmr_available_rjcode or row.display_rjcode or "").strip() if bool(row.has_asmr_one) else "暂无来源"
                status = "可下载" if (not bool(row.has_kikoeru) and bool(row.has_asmr_one)) else ("已满足" if bool(row.has_kikoeru) else "暂无来源")
                result.append({
                    "title": str(row.title or "").strip(),
                    "rjcode": str(row.display_rjcode or row.canonical_rjcode or "").strip(),
                    "kikoeru": kikoeru,
                    "dlsite": dlsite,
                    "asmr_one": asmr_one,
                    "status": status,
                })
            return result
        finally:
            db.close()
    except Exception:
        return []


def _build_circle_refresh_cards(circle_id: str, items: list) -> list[dict]:
    """把刷新结果转成邮件 RJ 卡片，并从 circle_works 补封面。"""
    enriched = _load_circle_work_map(circle_id, [
        str((item or {}).get("canonical_rjcode") or (item or {}).get("display_rjcode") or "").strip()
        for item in items
        if isinstance(item, dict)
    ])
    cards: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        canonical = str(item.get("canonical_rjcode") or "").strip().upper()
        display = str(item.get("display_rjcode") or canonical).strip().upper()
        row = enriched.get(canonical) or enriched.get(display) or {}
        rjcode = display or canonical or str(row.get("display_rjcode") or row.get("canonical_rjcode") or "").strip().upper()
        title = str(item.get("title") or row.get("title") or rjcode or "刷新作品").strip()
        changes = []
        for change in item.get("change_details") or []:
            if not isinstance(change, dict):
                continue
            label = str(change.get("label") or change.get("key") or "").strip()
            old = str(change.get("old") or "").strip() or "无"
            new = str(change.get("new") or "").strip() or "无"
            if label:
                changes.append(f"{label}: {old} -> {new}")
        if not changes:
            changes.append("状态无变化" if not item.get("changed") else "状态已更新")
        badges = []
        if item.get("changed"):
            badges.append("有更新")
        if item.get("has_kikoeru"):
            badges.append("服务器已有")
        if item.get("has_asmr_one"):
            badges.append("ASMR 可用")
        cards.append({
            "rjcode": rjcode or canonical,
            "title": title,
            "cover_url": str(row.get("image_url") or item.get("image_url") or item.get("cover_url") or "").strip(),
            "circle_name": str(row.get("maker_name") or "").strip(),
            "size_text": " / ".join(badges) if badges else "已刷新",
            "file_count": _safe_int(item.get("change_count")),
            "count_label": f"{_safe_int(item.get('change_count'))} 处变化" if _safe_int(item.get("change_count")) else "",
            "changes": changes[:6],
        })
    return cards


def _load_circle_work_map(circle_id: str, rjcodes: list[str]) -> dict[str, dict]:
    codes = {str(code or "").strip().upper() for code in rjcodes if str(code or "").strip()}
    if not codes:
        return {}
    try:
        from ..models.database import SessionLocal, CircleWork
        db = SessionLocal()
        try:
            query = db.query(CircleWork)
            if circle_id:
                query = query.filter(CircleWork.circle_id == circle_id)
            rows = query.filter(
                (
                    CircleWork.canonical_rjcode.in_(list(codes))
                ) | (
                    CircleWork.display_rjcode.in_(list(codes))
                ) | (
                    CircleWork.asmr_available_rjcode.in_(list(codes))
                )
            ).all()
            result: dict[str, dict] = {}
            for row in rows:
                data = row.to_dict()
                for key in (row.canonical_rjcode, row.display_rjcode, row.asmr_available_rjcode):
                    normalized = str(key or "").strip().upper()
                    if normalized:
                        result[normalized] = data
            return result
        finally:
            db.close()
    except Exception:
        return {}


def _norm_rel_path(value) -> str:
    """统一规整 relative_path：正斜杠、剥首尾斜杠。"""
    if not value:
        return ""
    s = str(value).replace("\\", "/").strip().strip("/")
    return s


def _build_filtered_path_set(filtered_items: list, filtered_files: list, filtered_dirs: list) -> set[str]:
    """把 filter_service 返回的过滤集合归一为 relative_path 集。

    filter_service 的 filtered_files / filtered_dirs 只是文件名 / 文件夹名（不带路径），
    filtered_items 才有完整 relative_path。这里三种都尽量收集，命中任意一种就标记。
    """
    out: set[str] = set()
    for item in filtered_items or []:
        if isinstance(item, dict):
            rel = _norm_rel_path(item.get("relative_path") or item.get("path") or item.get("name"))
            if rel:
                out.add(rel)
            name = _norm_rel_path(item.get("name"))
            if name:
                out.add(name)
        elif isinstance(item, str):
            out.add(_norm_rel_path(item))
    for name in filtered_files or []:
        if isinstance(name, str) and name:
            out.add(_norm_rel_path(name))
    for name in filtered_dirs or []:
        if isinstance(name, str) and name:
            out.add(_norm_rel_path(name))
    return {x for x in out if x}


def _build_uploaded_path_set(items: list) -> set[str]:
    """从 uploaded_files / failed_files 构建匹配集（rel + basename 都收）。"""
    out: set[str] = set()
    for item in items or []:
        if isinstance(item, dict):
            rel = _norm_rel_path(item.get("relative_path") or item.get("path") or item.get("upload_path") or item.get("target_path") or item.get("name"))
            if rel:
                out.add(rel)
                out.add(os.path.basename(rel))
            name = _norm_rel_path(item.get("name"))
            if name:
                out.add(name)
        elif isinstance(item, str):
            rel = _norm_rel_path(item)
            if rel:
                out.add(rel)
                out.add(os.path.basename(rel))
    return {x for x in out if x}


def _items_to_flat_rows(items: list, uploaded_set: set[str] | None = None, failed_set: set[str] | None = None, default_status: str = "kept") -> list[dict]:
    """通用：把 download_files / upload_files 之类扁平条目转成 flat row。

    - 命中 `uploaded_set` 的叶子打 `已上传` badge
    - 命中 `failed_set` 的叶子状态置 `removed` 并打 `下载失败` badge
    - 其它叶子使用 `default_status`
    """
    uploaded_set = uploaded_set or set()
    failed_set = failed_set or set()
    rows: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            if isinstance(item, str):
                rel = _norm_rel_path(item)
                if not rel:
                    continue
                base = os.path.basename(rel)
                badges = []
                status = default_status
                if rel in failed_set or base in failed_set:
                    status = "removed"
                    badges.append("下载失败")
                elif rel in uploaded_set or base in uploaded_set:
                    badges.append("已上传")
                rows.append({"rel": rel, "size": 0, "size_text": "", "status": status, "is_dir": False, "badges": badges})
            continue
        rel = _norm_rel_path(item.get("relative_path") or item.get("path") or item.get("upload_path") or item.get("target_path") or item.get("name"))
        if not rel:
            continue
        kind = (item.get("type") or ("dir" if item.get("children") else "file")).lower()
        is_dir = kind == "dir"
        base = _norm_rel_path(item.get("name") or os.path.basename(rel))

        size = item.get("size") or item.get("size_bytes") or 0
        try:
            size_int = int(size or 0)
        except Exception:
            size_int = 0

        badges: list[str] = []
        status = item.get("status") or default_status
        if not is_dir:
            if rel in failed_set or base in failed_set:
                status = "removed"
                badges.append("下载失败")
            elif rel in uploaded_set or base in uploaded_set:
                badges.append("已上传")

        rows.append({
            "rel": rel,
            "size": size_int,
            "size_text": item.get("size_text") or (_format_bytes(size_int) if size_int and not is_dir else ""),
            "status": status,
            "is_dir": is_dir,
            "badges": badges,
        })
    return rows


def _flatten_all_items(items: list, filtered_set: set[str]) -> list[dict]:
    """把 filter_service.all_items 转成统一扁平 row。

    返回：[{rel, size, size_text, status, is_dir}, ...]
    is_dir=True 的行表示空目录或被过滤目录，渲染时不计入文件计数。
    """
    rows: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            if isinstance(item, str):
                rel = _norm_rel_path(item)
                if rel:
                    rows.append({
                        "rel": rel,
                        "size": 0,
                        "size_text": "",
                        "status": "filtered" if rel in filtered_set or os.path.basename(rel) in filtered_set else "kept",
                        "is_dir": False,
                    })
            continue
        rel = _norm_rel_path(item.get("relative_path") or item.get("path") or item.get("name"))
        if not rel:
            continue
        kind = (item.get("type") or ("dir" if item.get("children") else "file")).lower()
        is_dir = kind == "dir"
        # 文件/目录是否在过滤集合：完整 rel 或末段 name 都查一次
        name = _norm_rel_path(item.get("name") or os.path.basename(rel))
        is_filtered = rel in filtered_set or (name and name in filtered_set)
        size = item.get("size") or item.get("size_bytes") or 0
        try:
            size_int = int(size or 0)
        except Exception:
            size_int = 0
        rows.append({
            "rel": rel,
            "size": size_int,
            "size_text": item.get("size_text") or (_format_bytes(size_int) if size_int and not is_dir else ""),
            "status": "filtered" if is_filtered else "kept",
            "is_dir": is_dir,
        })
    return rows


def _flat_to_tree(flat_rows: list[dict]) -> list[dict]:
    """扁平 path 列表 -> 嵌套目录树。

    给每个目录段建一个节点，文件挂到对应目录下。目录节点的 status 默认 kept，
    若它本身（rel 完整匹配）出现在 filtered_set 中也会被标 filtered。
    """
    if not flat_rows:
        return []

    # 用 (parent_rel, name) 去重 + 保持顺序
    root_children: dict = {}
    # 路径段 -> 节点 dict
    node_map: dict[str, dict] = {}

    def _ensure_dir(rel: str, status: str = "kept") -> dict:
        existing = node_map.get(rel)
        if existing:
            if status == "filtered":
                existing["status"] = "filtered"
            return existing
        parts = rel.split("/")
        parent_rel = "/".join(parts[:-1])
        name = parts[-1]
        node = {
            "name": name,
            "status": status,
            "_children_map": {},
            "children": [],
        }
        node_map[rel] = node
        if parent_rel:
            parent = _ensure_dir(parent_rel, status="kept")
            if name not in parent["_children_map"]:
                parent["_children_map"][name] = node
                parent["children"].append(node)
        else:
            if name not in root_children:
                root_children[name] = node
        return node

    # 先把所有目录建出来（包括隐含的中间路径）
    for row in flat_rows:
        rel = row["rel"]
        parts = rel.split("/")
        if row.get("is_dir"):
            _ensure_dir(rel, status=row.get("status") or "kept")
        else:
            # 中间各级目录用 kept 占位（叶子文件本身的 status 单独存）
            for i in range(1, len(parts)):
                _ensure_dir("/".join(parts[:i]), status="kept")

    # 再挂文件叶子
    for row in flat_rows:
        if row.get("is_dir"):
            continue
        rel = row["rel"]
        parts = rel.split("/")
        name = parts[-1]
        leaf = {
            "path": name,
            "size": row.get("size") or 0,
            "size_text": row.get("size_text") or "",
            "status": row.get("status") or "kept",
        }
        if row.get("badges"):
            leaf["badges"] = list(row["badges"])
        if len(parts) == 1:
            # 直接挂根
            root_children.setdefault(name, leaf)
            if root_children[name] is not leaf and isinstance(root_children[name], dict) and "children" in root_children[name]:
                # 重名冲突：忽略叶子
                continue
            root_children[name] = leaf
        else:
            parent_rel = "/".join(parts[:-1])
            parent = node_map.get(parent_rel)
            if parent is not None:
                parent["children"].append(leaf)

    # 输出：按目录在前 / 文件在后，名字字典序排
    def _emit(children_iter):
        dirs, files = [], []
        for child in children_iter:
            if isinstance(child, dict) and "children" in child:
                dirs.append(child)
            else:
                files.append(child)
        dirs.sort(key=lambda n: n.get("name", ""))
        files.sort(key=lambda n: n.get("path", ""))
        out = []
        for d in dirs:
            children_emitted = _emit(d["children"])
            out.append({
                "name": d["name"],
                "status": d["status"],
                "children": children_emitted,
            })
        out.extend(files)
        return out

    return _dedupe_redundant_tree_dirs(_emit(list(root_children.values())))


def _dedupe_redundant_tree_dirs(nodes: list[dict]) -> list[dict]:
    """压掉重复 RJ / 同名包装目录，保留一棵文件树和叶子状态。"""
    def _key(value: str) -> str:
        s = str(value or "").lower()
        s = s.replace("rj0", "rj").replace("rj", "")
        return "".join(ch for ch in s if ch.isalnum())

    def _walk(items: list[dict], parent_name: str = "") -> list[dict]:
        out = []
        parent_key = _key(parent_name)
        for item in items or []:
            if not isinstance(item, dict) or "children" not in item:
                out.append(item)
                continue
            name = str(item.get("name") or "")
            children = _walk(list(item.get("children") or []), name)
            current = {**item, "children": children}
            current_key = _key(name)
            if parent_key and current_key and (current_key == parent_key or current_key in parent_key or parent_key in current_key):
                out.extend(children)
            elif len(children) == 1 and isinstance(children[0], dict) and "children" in children[0]:
                child_name = str(children[0].get("name") or "")
                child_key = _key(child_name)
                if child_key and current_key and (child_key == current_key or child_key in current_key or current_key in child_key):
                    merged_status = "filtered" if "filtered" in {current.get("status"), children[0].get("status")} else current.get("status", "kept")
                    out.append({**children[0], "name": name or child_name, "status": merged_status})
                else:
                    out.append(current)
            else:
                out.append(current)
        return out

    return _walk(nodes)


def _normalize_file_tree(items: list, output_path: str) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        row = _normalize_tree_item(item, status="kept")
        if row:
            rows.append(row)
    if rows or not output_path:
        return rows
    if not os.path.isdir(output_path):
        return []
    base = output_path
    for root, dirs, files in os.walk(base):
        rel_root = os.path.relpath(root, base)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        if depth > 2:
            dirs[:] = []
            continue
        for name in files[:80]:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace("\\", "/")
            rows.append({
                "path": rel,
                "size": _safe_getsize(full),
                "size_text": _format_bytes(_safe_getsize(full)),
                "status": "kept",
            })
            if len(rows) >= 120:
                return rows
    return rows


def _normalize_tree_item(item, *, status: str) -> dict:
    if isinstance(item, dict):
        path = item.get("relative_path") or item.get("path") or item.get("name") or item.get("filename") or ""
        size = item.get("size") or item.get("size_bytes") or 0
        return {
            "path": str(path),
            "size": size,
            "size_text": item.get("size_text") or _format_bytes(size),
            "status": item.get("status") or status,
        }
    if isinstance(item, str):
        return {"path": item, "size_text": "", "status": status}
    return {}


def _count_files(items: list[dict]) -> int:
    return sum(1 for item in items if item and not item.get("children"))


def _sum_sizes(items: list[dict]) -> int:
    total = 0
    for item in items:
        try:
            total += int(item.get("size") or 0)
        except Exception:
            pass
    return total


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _format_circle_search_efficiency(works: Any, missing: Any) -> str:
    total = _safe_int(works)
    missing_count = _safe_int(missing)
    if total <= 0:
        return ""
    covered = max(0, total - missing_count)
    ratio = max(0.0, min(100.0, covered * 100.0 / total))
    return f"{ratio:.1f}%"


def _safe_getsize(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _count_files_on_disk(path: str) -> int:
    if not path or not os.path.isdir(path):
        return 0
    count = 0
    for _, _, files in os.walk(path):
        count += len(files)
    return count


def _sum_size_on_disk(path: str) -> int:
    if not path or not os.path.isdir(path):
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            total += _safe_getsize(os.path.join(root, name))
    return total


def _format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except Exception:
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def _format_duration(started_at, completed_at) -> str:
    if not started_at or not completed_at:
        return ""
    try:
        seconds = max(0, int((completed_at - started_at).total_seconds()))
    except Exception:
        return ""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {rest} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"
