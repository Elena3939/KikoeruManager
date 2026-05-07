from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, text
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict, deque
import contextlib
import json
import logging
import os
import sys
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import uuid
import yaml

# Create logger instance
logger = logging.getLogger(__name__)

from ..models.database import init_db, get_db, get_db_path_info, ActivityLog, ASMRDownloadSession, SessionLocal
from ..core.task_engine import TaskEngine, Task, TaskType, get_task_engine
from ..core.watcher import get_watcher
from ..core.password_cleanup import get_cleanup_service
from ..core.processed_archive_cleanup import get_processed_archive_cleanup_service
from ..core.backup_zip_service import get_backup_zip_service
from ..core.file_processor import get_file_processor
from ..core.library_manager import get_library_manager, SynologyError
from ..core.password_utils import (
    normalize_filename_value,
    normalize_optional_text,
    normalize_password_value,
    normalize_rjcode_value,
)
from ..config.settings import get_config, save_config

# 初始化FastAPI应用
app = FastAPI(
    title="Prekikoeru API",
    description="DLsite作品整理工具API",
    version="1.0.0"
)

# ========== 工具函数 ==========
def _synology_http_status(exc: Exception) -> int:
    """将群晖 API 错误码映射到合适的 HTTP 状态码。
    119: SID 过期/无效路径; 121: 无效参数; 401: 无权限; 408: 操作超时
    以上均视为上游服务（群晖）异常，返回 502 Bad Gateway。
    """
    msg = str(exc)
    for code in (119, 121, 401, 408):
        if re.search(rf'"code"\s*:\s*{code}\b', msg) or re.search(rf"'code'\s*:\s*{code}\b", msg):
            return 502
    return 500



def _log_synology_err(msg: str, exc: Exception) -> None:
    """群晖/认证可预期错误降级为 WARNING（不打堆栈）；其他意外错误仍用 ERROR + traceback。"""
    if isinstance(exc, SynologyError):
        logger.warning(msg)
    else:
        logger.error(msg, exc_info=True)

# ========== 健康检查 API ==========
@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "prekikoeru",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


# 注意：以下高频读接口刻意保持同步 def，让 FastAPI 调度到 starlette threadpool，
# 而不是 async def 直接占用事件循环。配合 run.py 的 anyio threadpool=80，群晖
# 慢 IO 场景下接口之间不再连环阻塞。
@app.get("/api/activity-logs")
def list_activity_logs(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    since_days: Optional[int] = None,
    batch_id: Optional[str] = None,
    session_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """分页查询操作审计记录。

    Phase 1/2 优化：
    - 原始查询强制加载上限（MAX_MERGE_WINDOW），避免随审计表无界增长拖慢接口。
    - 支持 since_days 指定仅合并最近 N 天；0/None=仅按 MAX 窗口截取。
    - 结果按 (筛选条件, 页码, writer.last_write_ts) TTL 缓存；有新审计写入时自动失效。
    - Phase 2：q 参数在存在 FTS5 虚表时优先走全文索引，命中后再按主键回查；
      不存在 FTS5 时回退为原来的 LIKE 多列匹配。
    - Phase 2：新增 batch_id / session_key 查询参数，用于 workbench 里
      "拉取某批次全部子任务"这种精准场景，直接走新索引。
    """
    from ..core.activity_log_service import CATEGORY_LABELS
    from ..core.activity_log_writer import (
        get_activity_log_query_cache,
        get_activity_log_row_dict_cache,
        get_activity_log_writer,
    )
    from ..models.database import activity_logs_fts_enabled

    MAX_MERGE_WINDOW = 5000
    writer = get_activity_log_writer()
    query_cache = get_activity_log_query_cache()
    cache_key = (
        "list",
        int(page or 1),
        int(limit or 50),
        (category or "").strip(),
        (status or "").strip(),
        (q or "").strip(),
        int(since_days) if since_days is not None else None,
        (batch_id or "").strip(),
        (session_key or "").strip(),
    )
    cached = query_cache.get(cache_key, writer.last_write_ts)
    if cached is not None:
        return cached

    # Phase 3: 1800+ 行合并算法已搬到 activity_log_aggregator 模块
    # Phase 4D: 用 merge_activity_rows_from_dicts 入口配合 row-dict 缓存，避免每请求重新
    # orjson.loads 所有 detail
    from ..core.activity_log_aggregator import merge_activity_rows_from_dicts

    page = max(1, page)
    limit = max(1, min(200, limit))
    query = db.query(ActivityLog)
    if category:
        query = query.filter(ActivityLog.category == category)
    if status:
        query = query.filter(ActivityLog.status == status)

    # Phase 2：精准过滤走新索引列，跳过合并 / FTS 分支
    batch_id_value = (batch_id or "").strip()
    if batch_id_value:
        query = query.filter(ActivityLog.batch_id == batch_id_value[:80])
    session_key_value = (session_key or "").strip()
    if session_key_value:
        query = query.filter(ActivityLog.session_key == session_key_value[:120])

    # Phase 2：q 参数的搜索路径
    # - FTS5 可用：先在 activity_logs_fts 上做 MATCH，命中 id 集合后回查主表；
    # - FTS5 不可用：退回到 Phase 1 的 LIKE 多列匹配
    search_backend = "none"
    search_text = (q or "").strip()
    if search_text:
        fts_ready = activity_logs_fts_enabled()
        if fts_ready:
            try:
                # 转义 FTS 保留字符：把双引号替换掉，再把整个串用双引号包起来走 phrase match
                safe = search_text.replace('"', ' ')
                match_expr = f'"{safe}"'
                fts_result = db.execute(
                    text("SELECT id FROM activity_logs_fts WHERE activity_logs_fts MATCH :term LIMIT :cap"),
                    {"term": match_expr, "cap": MAX_MERGE_WINDOW},
                )
                matched_ids = [row[0] for row in fts_result.fetchall() if row and row[0]]
                if matched_ids:
                    query = query.filter(ActivityLog.id.in_(matched_ids))
                    search_backend = "fts5"
                else:
                    # FTS 没命中任何 id，直接返回空
                    payload = {
                        "total": 0,
                        "page": page,
                        "limit": limit,
                        "items": [],
                        "window": {
                            "max_merge_window": MAX_MERGE_WINDOW,
                            "raw_loaded": 0,
                            "truncated": False,
                            "since_days": None,
                            "search_backend": "fts5",
                        },
                    }
                    query_cache.set(cache_key, writer.last_write_ts, payload)
                    return payload
            except Exception:
                logger.warning("[操作记录] FTS5 搜索失败，回退 LIKE", exc_info=True)
                fts_ready = False
        if not fts_ready:
            term = f"%{search_text}%"
            query = query.filter(
                or_(
                    ActivityLog.summary.like(term),
                    ActivityLog.rjcode.like(term),
                    ActivityLog.source_path.like(term),
                    ActivityLog.task_id.like(term),
                    ActivityLog.batch_id.like(term),
                )
            )
            search_backend = "like"

    # since_days=None: 默认仅合并 MAX_MERGE_WINDOW 条（按 created_at 倒序）；
    # since_days>0:   仅加载最近 N 天，配合上限兜底；
    # since_days=0:   显式放开时间过滤，仍有 MAX_MERGE_WINDOW 上限保护。
    effective_since_days = None
    if since_days is not None:
        try:
            sd = int(since_days)
        except (TypeError, ValueError):
            sd = None
        if sd is not None and sd > 0:
            effective_since_days = max(1, min(365, sd))
    if effective_since_days is not None:
        cutoff = datetime.now() - timedelta(days=effective_since_days)
        query = query.filter(ActivityLog.created_at >= cutoff)

    # Phase 4D：ID 先筛 → 行缓存命中 → 只拉未命中行。以前是 `.all()` 整列物化把所有 detail
    # JSON 都 orjson.loads 一遍（~90ms/762行，5000 行上 ~460ms）。现在稳态下 95%+ 请求
    # 能从 LRU 直接拿 row dict，整段下来只剩 ID 扫描 + 合并算法的 ~20ms 开销。
    ordered_id_rows = (
        query.with_entities(ActivityLog.id)
        .order_by(desc(ActivityLog.created_at))
        .limit(MAX_MERGE_WINDOW)
        .all()
    )
    ordered_ids = [row[0] for row in ordered_id_rows if row and row[0]]
    truncated = len(ordered_ids) >= MAX_MERGE_WINDOW

    row_cache = get_activity_log_row_dict_cache()
    cache_hits = row_cache.get_many(ordered_ids)
    missing_ids = [rid for rid in ordered_ids if str(rid) not in cache_hits]
    fresh_dict_map: Dict[str, Dict[str, Any]] = {}
    if missing_ids:
        fresh_orm_rows = (
            db.query(ActivityLog)
            .filter(ActivityLog.id.in_(missing_ids))
            .all()
        )
        fresh_pairs = []
        for orm_row in fresh_orm_rows:
            rid = str(orm_row.id)
            row_dict = orm_row.to_dict()
            fresh_dict_map[rid] = row_dict
            fresh_pairs.append((rid, row_dict))
        row_cache.put_many(fresh_pairs)

    rows_dict: List[Dict[str, Any]] = []
    for rid in ordered_ids:
        key = str(rid)
        row_dict = cache_hits.get(key) or fresh_dict_map.get(key)
        if row_dict is not None:
            rows_dict.append(row_dict)

    merged_items = merge_activity_rows_from_dicts(rows_dict)
    total = len(merged_items)
    start = (page - 1) * limit
    end = start + limit
    payload = {
        "total": total,
        "page": page,
        "limit": limit,
        "items": merged_items[start:end],
        "window": {
            "max_merge_window": MAX_MERGE_WINDOW,
            "raw_loaded": len(ordered_ids),
            "truncated": truncated,
            "since_days": effective_since_days,
            "search_backend": search_backend,
        },
    }
    query_cache.set(cache_key, writer.last_write_ts, payload)
    return payload


@app.get("/api/activity-logs/stats")
def activity_logs_stats(
    days: int = 14,
    db: Session = Depends(get_db),
):
    """按天、分类、状态聚合（用于图表）。

    Phase 1 优化：
    - 指标聚合不再整表读 detail JSON，改用 SQLite json_extract 只取用到的字段，
      省去全列 deserialize 带来的 IO + 反序列化成本。
    - 聚合结果按 (days, writer.last_write_ts) TTL 缓存（30s），读多写少场景命中率高。
    """
    from ..core.activity_log_service import CATEGORY_LABELS
    from ..core.activity_log_writer import (
        get_activity_log_query_cache,
        get_activity_log_writer,
    )

    days = int(days)
    all_time = days <= 0
    days = 0 if all_time else max(1, min(90, days))

    writer = get_activity_log_writer()
    query_cache = get_activity_log_query_cache()
    cache_key = ("stats", days, bool(all_time))
    cached = query_cache.get(cache_key, writer.last_write_ts)
    if cached is not None:
        return cached

    cutoff = None if all_time else (datetime.now() - timedelta(days=days))
    cutoff_date_str = None if cutoff is None else cutoff.strftime("%Y-%m-%d")

    # Phase 4A：by_day / by_category / by_status 改读 activity_log_daily_stats 聚合表，
    # 不再扫 activity_logs 全表做 GROUP BY。聚合表由 Writer 增量维护 + 启动时回填。
    from ..models.database import ActivityLogDailyStats

    rollup_query = db.query(
        ActivityLogDailyStats.date,
        ActivityLogDailyStats.category,
        ActivityLogDailyStats.status,
        ActivityLogDailyStats.count,
    )
    if cutoff_date_str is not None:
        rollup_query = rollup_query.filter(ActivityLogDailyStats.date >= cutoff_date_str)
    rollup_rows = rollup_query.all()

    by_day_map: Dict[str, int] = {}
    cat_counter: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for date_str, cat, st, cnt in rollup_rows:
        if not date_str:
            continue
        n = int(cnt or 0)
        by_day_map[date_str] = by_day_map.get(date_str, 0) + n
        if cat:
            cat_counter[cat] = cat_counter.get(cat, 0) + n
        if st:
            by_status[str(st)] = by_status.get(str(st), 0) + n
    by_day = [{"date": d, "count": c} for d, c in sorted(by_day_map.items())]
    by_category = [
        {"category": c, "label": CATEGORY_LABELS.get(c, c), "count": n}
        for c, n in sorted(cat_counter.items(), key=lambda kv: -kv[1])
    ]
    total_in_range = sum(by_status.values())

    # 只选指标计算用得上的字段（category/action/status + detail.* 单项），
    # 避免把整个 detail JSON 拉回 Python 做反序列化。
    def _jx(path: str):
        return func.json_extract(ActivityLog.detail, f"$.{path}")

    metric_query = db.query(
        ActivityLog.category,
        ActivityLog.action,
        ActivityLog.status,
        _jx("downloaded_count"),
        _jx("applied_pairs"),
        _jx("manual_match_applied_pairs"),
        _jx("matched_group_count"),
        _jx("final_file_count"),
        _jx("extract_output_bytes"),
        _jx("output_size_bytes"),
        _jx("extract_performed"),
        _jx("archive_input"),
        _jx("success_count"),
        _jx("deleted_bytes"),
    )
    if cutoff is not None:
        metric_query = metric_query.filter(ActivityLog.created_at >= cutoff)
    # 只对会贡献指标的 category 做过滤，进一步缩小扫描面
    relevant_categories = {
        "subtitle_crawl", "subtitle_pair", "subtitle_import",
        "extract", "auto_import",
        "pipeline_filter", "pipeline_delete",
    }
    metric_query = metric_query.filter(ActivityLog.category.in_(relevant_categories))
    metric_rows = metric_query.all()

    def _int(value: Any) -> int:
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0

    def _truthy(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "null", "none"}
        return bool(value)

    metrics = {
        "subtitle_download_count": 0,
        "subtitle_match_count": 0,
        "subtitle_crawl_count": 0,
        "subtitle_import_count": 0,
        "extract_count": 0,
        "delete_count": 0,
        "delete_bytes": 0,
        "extract_bytes": 0,
    }
    for (
        category,
        action,
        status,
        downloaded_count,
        applied_pairs,
        manual_match_applied_pairs,
        matched_group_count,
        final_file_count,
        extract_output_bytes,
        output_size_bytes,
        extract_performed,
        archive_input,
        success_count,
        deleted_bytes,
    ) in metric_rows:
        if status not in {"success", "completed", "partial_success"}:
            continue
        if category == "subtitle_crawl":
            metrics["subtitle_crawl_count"] += 1
            metrics["subtitle_download_count"] += _int(downloaded_count)
        elif category == "subtitle_pair":
            metrics["subtitle_match_count"] += (
                _int(applied_pairs)
                or _int(manual_match_applied_pairs)
                or _int(matched_group_count)
                or _int(final_file_count)
                or 0
            )
        elif category == "subtitle_import":
            metrics["subtitle_import_count"] += _int(final_file_count) or 1
        elif category == "extract":
            metrics["extract_count"] += 1
            metrics["extract_bytes"] += _int(extract_output_bytes) or _int(output_size_bytes)
        elif category == "auto_import":
            if _truthy(extract_performed) or _truthy(archive_input):
                metrics["extract_count"] += 1
                metrics["extract_bytes"] += _int(extract_output_bytes) or _int(output_size_bytes)
        elif category == "pipeline_filter" and action == "filter_delete_apply":
            metrics["delete_count"] += _int(success_count)
            metrics["delete_bytes"] += _int(deleted_bytes)
        elif category == "pipeline_delete":
            if action == "batch_api_delete":
                metrics["delete_count"] += _int(success_count)
            elif action in {"delete", "batch_delete_item"} and status in {"success", "completed"}:
                metrics["delete_count"] += 1

    payload = {
        "days": days,
        "total_in_range": total_in_range,
        "by_day": by_day,
        "by_category": by_category,
        "by_status": by_status,
        "metrics": metrics,
        "db_path": get_db_path_info(),
    }
    query_cache.set(cache_key, writer.last_write_ts, payload)
    return payload


@app.post("/api/activity-logs/filter-delete")
async def create_filter_delete_activity_log(request: Request):
    """写入删除过滤预审 / 执行的操作记录。"""
    from ..core.activity_log_service import (
        log_filter_delete_apply_result,
        log_filter_delete_preview_result,
        log_filter_delete_retry_result,
    )

    try:
        data = await request.json()
        mode = str(data.get("mode") or "").strip()
        if mode == "preview":
            log_filter_delete_preview_result(data)
        elif mode == "retry_preview":
            log_filter_delete_retry_result(data)
        elif mode == "apply":
            log_filter_delete_apply_result(data)
        else:
            raise HTTPException(status_code=400, detail="不支持的删除过滤日志类型")
        return {"message": "操作记录已写入"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"写入删除过滤操作记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"写入删除过滤操作记录失败: {str(e)}")


@app.get("/api/activity-logs/{log_id}/children")
def get_activity_log_children(
    log_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """懒拉取某条操作记录下挂的全部子记录。

    Phase 3：前端查看批量任务（解压入库 / 社团下载 / 字幕抓取批次等）详情时，
    不再需要把整窗口 5000 行一次性拉回来交给合并算法拆分；
    直接按 Phase 2 新建的 ``batch_id`` / ``session_key`` 索引做单次 SQL 查询即可。

    匹配策略（按优先级回退）：
    1. 当前行自身的 ``batch_id`` 命中其他行的 ``batch_id``
    2. 当前行的 ``id`` 命中其他行的 ``parent_id``
    3. 当前行的 ``session_key`` 命中其他行的 ``session_key``
    """
    from ..core.activity_log_aggregator import merge_activity_rows

    limit = max(1, min(1000, int(limit or 200)))
    parent = db.query(ActivityLog).filter(ActivityLog.id == log_id).first()
    if parent is None:
        raise HTTPException(status_code=404, detail="未找到对应操作记录")

    children: List[ActivityLog] = []
    seen_ids = {parent.id}

    def _extend(rows):
        for row in rows:
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            children.append(row)

    if parent.batch_id:
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.batch_id == parent.batch_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(limit)
            .all()
        )

    if len(children) < limit:
        remaining = limit - len(children)
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.parent_id == parent.id)
            .order_by(desc(ActivityLog.created_at))
            .limit(remaining)
            .all()
        )

    if len(children) < limit and parent.session_key:
        remaining = limit - len(children)
        _extend(
            db.query(ActivityLog)
            .filter(ActivityLog.session_key == parent.session_key)
            .order_by(desc(ActivityLog.created_at))
            .limit(remaining)
            .all()
        )

    # 复用聚合器规范化 to_dict + category_label 等字段，保证和列表接口 item 结构一致
    parent_item = merge_activity_rows([parent])
    child_items = merge_activity_rows(children) if children else []
    return {
        "parent": parent_item[0] if parent_item else parent.to_dict(),
        "total": len(child_items),
        "items": child_items,
        "match": {
            "by_batch_id": parent.batch_id,
            "by_parent_id": parent.id,
            "by_session_key": parent.session_key,
        },
    }


@app.post("/api/activity-logs/backfill-auto-import-extract")
async def backfill_auto_import_extract_activity_logs(
    start_offset: int = 0,
    chunk_size: int = 200,
    max_rows: Optional[int] = None,
    time_budget_seconds: float = 8.0,
):
    """分片回填旧导入链操作记录中的解压字段与文件树。

    Phase 1：不再一次性全表扫描 + os.walk，改为 offset 分片 + 时间预算。
    若返回 done=false，前端应带 next_offset 再次调用直到 done=true。
    """
    from ..core.activity_log_service import backfill_auto_import_extract_fields

    try:
        result = backfill_auto_import_extract_fields(
            chunk_size=chunk_size,
            start_offset=start_offset,
            max_rows=max_rows,
            time_budget_seconds=time_budget_seconds,
        )
        return {
            "message": (
                "导入链操作记录字段与文件树回填完成"
                if result.get("done")
                else f"本轮处理 {result.get('scanned')} 行，未完成，请带 next_offset 继续"
            ),
            **result,
        }
    except Exception as e:
        logger.error(f"回填导入链操作记录字段失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"回填导入链操作记录字段失败: {str(e)}")


# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 通知定期清理协程（每24h清一次超7天的已读通知）
async def _periodic_notification_cleanup():
    while True:
        try:
            await asyncio.sleep(24 * 3600)
            from ..core.task_notification_service import cleanup_old_notifications
            deleted = cleanup_old_notifications(retain_days=7)
            if deleted > 0:
                logger.info(f"[通知清理] 已清理 {deleted} 条超过7天的旧通知")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[通知清理] 定期清理异常: {e}")


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    # 抬高 starlette 默认 threadpool 上限：FastAPI 的同步路由（def 而非 async def）
    # 都跑在这个池里，默认 40 在群晖 + SMB + 多任务并发时容易顶满，连环超时。
    # 80 对单实例桌面 / 中小 NAS 已经很宽裕，CPU / 内存压力可控。
    try:
        from anyio import to_thread as _anyio_to_thread
        _anyio_to_thread.current_default_thread_limiter().total_tokens = 80
    except Exception:
        logger.warning("[启动] 调整 anyio threadpool 上限失败，沿用默认值", exc_info=True)

    # 初始化数据库
    init_db()

    # 启动任务引擎
    engine = get_task_engine()
    engine.start()

    # 如果配置了自动启动监视器，则启动
    config = get_config()
    if config.watcher.enabled:
        watcher = get_watcher()
        watcher.start()

    # 启动密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.start()

    # 启动已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.start()

    # 扫描已处理压缩包目录，同步数据库（根据配置决定是否启用）
    config = get_config()
    if config.processed_archive_cleanup.scan_on_startup:
        await scan_processed_archives()
    else:
        logger.info("启动时扫描已处理压缩包目录已禁用")

    # 启动 DLsite 邮件监听服务（IMAP IDLE）
    from ..core.email_watcher_service import get_email_watcher_service
    email_watcher = get_email_watcher_service()
    await email_watcher.start()

    # 启动通知中心 outbox 发件 worker
    from ..core.notification_template_service import ensure_default_email_templates
    ensure_default_email_templates()
    from ..core.task_notification_service import start_outbox_worker
    asyncio.create_task(start_outbox_worker())

    # 启动通知定期清理任务（每天清理超7天的旧通知）
    asyncio.create_task(_periodic_notification_cleanup())

# 关闭事件
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    # 停止 DLsite 邮件监听服务
    from ..core.email_watcher_service import get_email_watcher_service
    await get_email_watcher_service().stop()

    # 停止任务引擎
    engine = get_task_engine()
    engine.stop()

    # 停止监视器
    watcher = get_watcher()
    watcher.stop()

    # 停止密码库智能清理服务
    cleanup_service = get_cleanup_service()
    await cleanup_service.stop()

    # 停止已处理压缩包智能清理服务
    archive_cleanup_service = get_processed_archive_cleanup_service()
    await archive_cleanup_service.stop()

    # Flush 操作记录后台写入器，确保任务 finally 刚入队的审计不丢
    try:
        from ..core.activity_log_writer import (
            shutdown_activity_log_writer,
            shutdown_lifecycle_executor,
        )
        shutdown_lifecycle_executor(timeout=5.0)
        shutdown_activity_log_writer(timeout=5.0)
    except Exception:
        logger.warning("关闭操作记录写入器失败", exc_info=True)

# Pydantic模型
class TaskCreate(BaseModel):
    source_path: str
    task_type: str = "auto_process"
    auto_classify: bool = True
    target_library_id: Optional[str] = None

class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    source_path: str
    output_path: Optional[str]
    progress: int
    current_step: str
    error_message: Optional[str]
    rjcode: Optional[str] = None
    
    class Config:
        from_attributes = True


class TaskCenterOverviewResponse(BaseModel):
    generated_at: str
    total: int
    counts_by_domain: Dict[str, int]
    counts_by_status: Dict[str, int]
    highlight_counts: Dict[str, int]
    recent_items: List[Dict[str, Any]]
    active_items: List[Dict[str, Any]]


class TaskCenterListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    offset: int
    limit: int
    mode: str
    generated_at: str


class TaskCenterItemResponse(BaseModel):
    id: str
    entity_id: str
    engine_task_id: Optional[str] = None
    record_id: Optional[str] = None
    domain: str
    domain_label: str
    kind: str
    kind_label: str
    title: str
    subtitle: str
    source_label: str
    source_page: str
    source_action: str
    route_hint: str
    status: str
    status_label: str
    progress: int
    current_step: str
    error_message: str
    source_path: str
    target_path: str
    rjcode: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metrics: List[Dict[str, str]]
    actions: List[str]
    details: Dict[str, Any]


class TaskCenterActionRequest(BaseModel):
    action: str

class ConfigResponse(BaseModel):
    storage: dict
    processing: dict
    watcher: dict
    extract: Optional[dict] = None
    filter: dict
    metadata: dict
    rename: dict
    classification: list
    password_cleanup: Optional[dict] = None
    processed_archive_cleanup: Optional[dict] = None
    path_mapping: Optional[dict] = None
    kikoeru_server: Optional[dict] = None
    asmr_sync: Optional[dict] = None
    auto_process: Optional[dict] = None
    process_existing: Optional[dict] = None
    asmr_sync_step: Optional[dict] = None
    rj_subtitle: Optional[dict] = None
    backup_zip: Optional[dict] = None
    email_watcher: Optional[dict] = None
    notification_email: Optional[dict] = None
    notification_center: Optional[dict] = None

# API路由
# 兼容层：旧任务接口仅保留给少数历史入口使用，新功能统一走 /api/task-center/*
@app.post("/api/tasks", response_model=TaskResponse, deprecated=True, summary="兼容层：创建原始引擎任务")
async def create_task(task_create: TaskCreate):
    """兼容层：创建原始引擎任务，新功能请改用任务中心聚合接口。"""
    from ..core.file_processor import get_file_processor

    file_processor = get_file_processor()
    config = get_config()

    # 使用 FileProcessor 处理文件
    task = await file_processor.process_file(
        task_create.source_path,
        auto_classify=task_create.auto_classify,
        wait_stable=False,  # 手动创建任务时不等待稳定
        is_processed=lambda path: False,  # 允许重新处理
        mark_processed=None
    )

    if not task:
        raise HTTPException(status_code=400, detail=f"无法处理文件: {task_create.source_path}")

    if task_create.target_library_id:
        task.task_metadata["target_library_id"] = task_create.target_library_id

    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        source_path=task.source_path,
        output_path=task.output_path,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        rjcode=task.rjcode
    )

# ========== 文件上传 API ==========
@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), target_library_id: Optional[str] = Form(None)):
    """上传文件并触发扫描（复用分卷识别逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 确保输入目录存在
    os.makedirs(input_path, exist_ok=True)

    uploaded_files = []

    for file in files:
        if not file.filename:
            continue

        # 保存文件到输入目录
        file_path = os.path.join(input_path, file.filename)

        _file_obj = file.file

        def _write_upload():
            with open(file_path, "wb") as _buf:
                shutil.copyfileobj(_file_obj, _buf)

        await asyncio.to_thread(_write_upload)

        uploaded_files.append(file_path)
        logger.info(f"上传文件: {file.filename} -> {file_path}")

    # 不再为每个文件单独创建任务
    # 改为调用扫描逻辑，复用分卷文件识别
    # 扫描逻辑会正确识别分卷文件，只为主文件创建任务
    scan_result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="upload_scan",
        source_label="仪表盘 / 上传后扫描",
        target_library_id=target_library_id,
    )
    if target_library_id and scan_result["task_ids"]:
        engine = get_task_engine()
        for task_id in scan_result["task_ids"]:
            task = engine.get_task(task_id)
            if task:
                task.task_metadata["target_library_id"] = target_library_id

    return {
        "message": f"成功上传 {len(uploaded_files)} 个文件，{scan_result['message']}",
        "uploaded_count": len(uploaded_files),
        "found_count": scan_result["found_count"],
        "task_ids": scan_result["task_ids"]
    }


async def _scan_and_create_tasks(
    *,
    source_page: str = "dashboard",
    source_action: str = "scan_input",
    source_label: str = "仪表盘 / 扫描导入",
    target_library_id: Optional[str] = None,
):
    """扫描输入目录并创建任务（使用 FileProcessor 统一处理逻辑）"""
    config = get_config()
    input_path = config.storage.input_path

    # 自动创建目录（如果不存在）
    if not os.path.exists(input_path):
        try:
            os.makedirs(input_path, exist_ok=True)
            logger.info(f"自动创建输入目录: {input_path}")
        except Exception as e:
            return {"message": f"无法创建输入目录: {str(e)}", "found_count": 0, "task_ids": []}

    watcher = get_watcher()
    file_processor = get_file_processor()
    from ..core.activity_log_service import log_import_batch_start_result

    batch_id = str(uuid.uuid4())
    batch_context = {
        "batch_id": batch_id,
        "session_id": batch_id,
        "batch_title": "批量解压入库",
        "batch_label": "解压入库批次",
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "log_parent": True,
    }
    report: dict[str, Any] = {
        "requested_count": 0,
        "created_count": 0,
        "skipped_processed_count": 0,
        "skipped_duplicate_count": 0,
    }

    # 使用 FileProcessor 统一处理目录
    tasks = await file_processor.process_directory(
        input_path,
        auto_classify=config.watcher.auto_classify,
        is_processed=lambda path: (
            path in watcher.pending_files or
            path in watcher._processed_files or
            any(t.source_path == path and t.status.value in ["pending", "processing"]
                for t in get_task_engine().get_all_tasks())
        ),
        mark_processed=watcher._mark_file_processed,
        task_metadata={"target_library_id": target_library_id} if target_library_id else None,
        batch_context=batch_context,
        report=report,
    )

    created_task_ids = [task.id for task in tasks]
    requested_count = int(report.get("requested_count") or len(tasks))
    created_tasks = [{"task_id": task.id, "source_path": task.source_path} for task in tasks]
    log_import_batch_start_result({
        "batch_id": batch_id,
        "requested_count": requested_count,
        "created_count": len(tasks),
        "skipped_total": int(report.get("skipped_processed_count") or 0) + int(report.get("skipped_duplicate_count") or 0),
        "skipped_processed": int(report.get("skipped_processed_count") or 0),
        "skipped_duplicate": int(report.get("skipped_duplicate_count") or 0),
        "archive_count": requested_count,
        "extracted_count": len(tasks),
        "auto_classify": bool(config.watcher.auto_classify),
        "target_library_id": target_library_id,
        "source_page": source_page,
        "source_action": source_action,
        "source_label": source_label,
        "source_paths": [task.source_path for task in tasks],
        "created_tasks": created_tasks,
        "skipped_items": [],
        "source_path": input_path,
    })

    return {
        "message": f"找到 {len(tasks)} 个待处理文件",
        "found_count": len(tasks),
        "task_ids": created_task_ids,
        "batch_id": batch_id,
    }

@app.get("/api/backup/history")
def get_backup_history():
    """获取备份历史记录"""
    from ..models.database import BackupRecord, get_db
    
    db = next(get_db())
    try:
        records = db.query(BackupRecord).order_by(desc(BackupRecord.created_at)).all()
        return [record.to_dict() for record in records]
    finally:
        db.close()

@app.get("/api/tasks", response_model=List[TaskResponse], deprecated=True, summary="兼容层：获取原始引擎任务列表")
async def get_tasks(status: Optional[str] = None):
    """兼容层：获取原始引擎任务列表，新功能请改用 /api/task-center/list。"""
    engine = get_task_engine()
    
    if status == "pending":
        tasks = engine.get_pending_tasks()
    elif status == "processing":
        tasks = engine.get_processing_tasks()
    elif status == "completed":
        tasks = engine.get_completed_tasks()
    else:
        tasks = engine.get_all_tasks()
    
    return [
        TaskResponse(
            id=task.id,
            type=task.type.value,
            status=task.status.value,
            source_path=task.source_path,
            output_path=task.output_path,
            progress=task.progress,
            current_step=task.current_step,
            error_message=task.error_message,
            rjcode=task.rjcode
        )
        for task in tasks
    ]


@app.get("/api/task-center/overview", response_model=TaskCenterOverviewResponse)
async def get_task_center_overview():
    """获取任务中心总览摘要。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.get_overview()


@app.get("/api/task-center/list", response_model=TaskCenterListResponse)
async def get_task_center_list(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    mode: str = "detail",
    offset: int = 0,
    limit: int = 200,
):
    """获取任务中心统一任务列表。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.list_items(domain=domain, status=status, search=search, mode=mode, offset=offset, limit=limit)


@app.get("/api/task-center/item", response_model=Optional[TaskCenterItemResponse])
async def get_task_center_item(item_id: Optional[str] = None, engine_task_id: Optional[str] = None):
    """按任务中心 ID 或引擎任务 ID 获取单项。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.get_item(item_id=item_id, engine_task_id=engine_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/task-center/diagnose")
async def diagnose_task_center_serialization():
    """诊断任务中心聚合中具体是哪条数据序列化失败。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    return await service.diagnose_serialization_failures()


@app.post("/api/task-center/{item_id}/action")
async def execute_task_center_action(item_id: str, payload: TaskCenterActionRequest):
    """执行任务中心统一动作。"""
    from ..core.task_center_service import get_task_center_service

    service = get_task_center_service()
    try:
        return await service.execute_action(item_id, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/tasks/{task_id}", response_model=TaskResponse, deprecated=True, summary="兼容层：获取原始引擎任务")
async def get_task(task_id: str):
    """兼容层：获取原始引擎任务详情，新功能请改用 /api/task-center/item。"""
    engine = get_task_engine()
    task = engine.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    
    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        source_path=task.source_path,
        output_path=task.output_path,
        progress=task.progress,
        current_step=task.current_step,
        error_message=task.error_message,
        rjcode=task.rjcode
    )

@app.post("/api/tasks/{task_id}/pause", deprecated=True, summary="兼容层：暂停原始引擎任务")
async def pause_task(task_id: str):
    """兼容层：暂停原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.pause_task(task_id)
    return {"message": "任务已暂停"}

@app.post("/api/tasks/{task_id}/resume", deprecated=True, summary="兼容层：恢复原始引擎任务")
async def resume_task(task_id: str):
    """兼容层：恢复原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.resume_task(task_id)
    return {"message": "任务已恢复"}

@app.post("/api/tasks/{task_id}/cancel", deprecated=True, summary="兼容层：取消原始引擎任务")
async def cancel_task(task_id: str):
    """兼容层：取消原始引擎任务，新动作请改用 /api/task-center/{id}/action。"""
    engine = get_task_engine()
    engine.cancel_task(task_id)
    return {"message": "任务已取消"}

@app.post("/api/tasks/batch-cancel-cleanup", summary="批量取消任务并清理已下载文件")
async def batch_cancel_cleanup(request: Request):
    """批量取消任务并删除对应的已下载临时文件。"""
    import shutil
    from ..core.task_engine import TaskStatus
    body = await request.json()
    task_ids = body.get("task_ids") or []
    if not task_ids:
        return {"cancelled": 0, "cleaned": 0}
    engine = get_task_engine()
    cancelled = 0
    cleaned = 0
    for tid in task_ids:
        task = engine.get_task(str(tid))
        if not task:
            continue
        if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED):
            engine.cancel_task(str(tid))
            cancelled += 1
        download_root = str(
            getattr(task, "task_metadata", {}).get("download_root")
            or getattr(task, "source_path", "")
            or ""
        ).strip()
        if download_root and os.path.isdir(download_root):
            try:
                _robust_rmtree(download_root)
                cleaned += 1
                logger.info(f"已清理下载目录: {download_root}")
            except Exception:
                logger.warning(f"清理下载目录失败: {download_root}")
    return {"cancelled": cancelled, "cleaned": cleaned, "message": f"已取消 {cancelled} 个任务，清理 {cleaned} 个下载目录"}

def _mask_notification_email_config(config) -> Optional[dict]:
    """返回 notification_email 配置，密码脱敏"""
    if not hasattr(config, 'notification_email'):
        return None
    data = config.notification_email.model_dump()
    if data.get('password'):
        data['password'] = '********'
    return data


def _read_notification_email_password_from_disk() -> str:
    """读取磁盘原始配置，避免把前端脱敏占位符写回真实配置。"""
    try:
        from ..config.settings import get_config_file_path

        config_path = get_config_file_path()
        if not os.path.exists(config_path):
            return ""
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        password = data.get("notification_email", {}).get("password", "")
        return password if password != "********" else ""
    except Exception:
        logger.warning("[NOTIFICATION] 读取磁盘 notification_email 密码失败", exc_info=True)
        return ""


@app.get("/api/config", response_model=ConfigResponse)
def get_configuration():
    """获取配置"""
    config = get_config()
    storage_data = config.storage.model_dump()
    library_cfg = get_library_manager().load_config()
    storage_data["default_library_id"] = library_cfg["default_library_id"]
    storage_data["default_extract_library_id"] = library_cfg["default_extract_library_id"]
    storage_data["health_warning_free_gb"] = library_cfg["health_warning_free_gb"]
    storage_data["stats_cache_ttl_seconds"] = library_cfg["stats_cache_ttl_seconds"]
    return ConfigResponse(
        storage=storage_data,
        processing=config.processing.model_dump(),
        watcher=config.watcher.model_dump(),
        extract=config.extract.model_dump(),
        filter=config.filter.model_dump(),
        metadata=config.metadata.model_dump(),
        rename=config.rename.model_dump(),
        classification=[rule.model_dump() for rule in config.classification],
        password_cleanup=config.password_cleanup.model_dump(),
        processed_archive_cleanup=config.processed_archive_cleanup.model_dump(),
        path_mapping=config.path_mapping.model_dump(),
        kikoeru_server=config.kikoeru_server.model_dump() if hasattr(config, 'kikoeru_server') else None,
        asmr_sync=config.asmr_sync.model_dump() if hasattr(config, 'asmr_sync') else None,
        auto_process=config.auto_process.model_dump() if hasattr(config, 'auto_process') else None,
        process_existing=config.process_existing.model_dump() if hasattr(config, 'process_existing') else None,
        asmr_sync_step=config.asmr_sync_step.model_dump() if hasattr(config, 'asmr_sync_step') else None,
        rj_subtitle=config.rj_subtitle.model_dump() if hasattr(config, 'rj_subtitle') else None,
        backup_zip=config.backup_zip.model_dump() if hasattr(config, 'backup_zip') else None,
        email_watcher=config.email_watcher.model_dump() if hasattr(config, 'email_watcher') else None,
        notification_email=_mask_notification_email_config(config),
        notification_center=config.notification_center.model_dump() if hasattr(config, 'notification_center') else None,
    )

@app.get("/api/config/state")
def get_configuration_state():
    """获取配置运行态，便于排查首屏配置抖动。"""
    from ..config.settings import get_config_runtime_state

    return get_config_runtime_state()

@app.post("/api/config")
async def update_configuration(request: Request):
    """更新配置"""
    from ..config.settings import save_config, ClassificationRule, FilterRule, PathMappingRule
    try:
        config_data = await request.json()
        logger.info(f"接收到配置保存请求，classification: {config_data.get('classification')}")
        
        # 记录重命名模板用于调试
        if 'rename' in config_data and config_data['rename']:
            template = config_data['rename'].get('template', 'NOT SET')
            logger.info(f"[CONFIG SAVE] 接收到的模板: '{template}'")
        
        # 确保 classification 字段格式正确
        if 'classification' in config_data and config_data['classification']:
            validated_rules = []
            for rule_data in config_data['classification']:
                try:
                    # 清理 None 值
                    rule_data_cleaned = {k: v for k, v in rule_data.items() if v is not None}
                    # 使用 Pydantic 验证每个规则
                    rule = ClassificationRule(**rule_data_cleaned)
                    validated_rules.append(rule.dict())
                    logger.info(f"规则验证通过: {rule_data_cleaned}")
                except Exception as e:
                    logger.warning(f"分类规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['classification'] = validated_rules
            logger.info(f"验证后的分类规则: {validated_rules}")
        
        # 确保 filter 字段格式正确
        if 'filter' in config_data and config_data['filter'] and 'rules' in config_data['filter']:
            validated_filter_rules = []
            for rule_data in config_data['filter']['rules']:
                try:
                    # 确保 target 字段存在
                    if 'target' not in rule_data or not rule_data['target']:
                        rule_data['target'] = 'file'
                    # 使用 Pydantic 验证
                    rule = FilterRule(**rule_data)
                    validated_filter_rules.append(rule.dict())
                    logger.info(f"过滤规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"过滤规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['filter']['rules'] = validated_filter_rules
            logger.info(f"验证后的过滤规则数: {len(validated_filter_rules)}")
        
        # 确保 path_mapping 字段格式正确
        if 'path_mapping' in config_data and config_data['path_mapping'] and 'rules' in config_data['path_mapping']:
            validated_path_rules = []
            for rule_data in config_data['path_mapping']['rules']:
                try:
                    rule = PathMappingRule(**rule_data)
                    validated_path_rules.append(rule.dict())
                    logger.info(f"路径映射规则验证通过: {rule_data}")
                except Exception as e:
                    logger.warning(f"路径映射规则验证失败: {rule_data}, 错误: {e}")
                    # 跳过无效规则
            config_data['path_mapping']['rules'] = validated_path_rules
            logger.info(f"验证后的路径映射规则数: {len(validated_path_rules)}")
        
        # 处理 Kikoeru 服务器配置
        if 'kikoeru_server' in config_data:
            logger.info(f"[KIKOERU] 接收到 Kikoeru 服务器配置: {config_data['kikoeru_server']}")
            try:
                # 验证 KikoeruServerConfig
                from ..config.settings import KikoeruServerConfig
                kikoeru_config = KikoeruServerConfig(**config_data['kikoeru_server'])
                config_data['kikoeru_server'] = kikoeru_config.model_dump()
                logger.info(f"[KIKOERU] 配置验证通过: enabled={kikoeru_config.enabled}, server_url={kikoeru_config.server_url}")
            except Exception as e:
                logger.error(f"[KIKOERU] Kikoeru 配置验证失败: {e}")
                # 如果验证失败，保留原始配置
        else:
            logger.info("[KIKOERU] 未接收到 Kikoeru 服务器配置")

        # 处理 ASMR 同步配置
        if 'asmr_sync' in config_data:
            logger.info(f"[ASMR] 接收到 ASMR 同步配置: {config_data['asmr_sync']}")
            try:
                from ..config.settings import ASMRSyncConfig
                asmr_config = ASMRSyncConfig(**config_data['asmr_sync'])
                config_data['asmr_sync'] = asmr_config.model_dump()
                logger.info(f"[ASMR] 配置验证通过: retry_cron={asmr_config.retry_cron}")
            except Exception as e:
                logger.error(f"[ASMR] ASMR 同步配置验证失败: {e}")
        else:
            logger.info("[ASMR] 未接收到 ASMR 同步配置")

        if 'backup_zip' in config_data:
            try:
                from ..config.settings import BackupZipConfig
                backup_zip_config = BackupZipConfig(**config_data['backup_zip'])
                config_data['backup_zip'] = backup_zip_config.model_dump()
            except Exception as e:
                logger.error(f"[BACKUP_ZIP] 配置验证失败: {e}")

        if 'rj_subtitle' in config_data:
            try:
                from ..config.settings import RJSubtitleConfig
                rj_subtitle_config = RJSubtitleConfig(**config_data['rj_subtitle'])
                config_data['rj_subtitle'] = rj_subtitle_config.model_dump()
            except Exception as e:
                logger.error(f"[RJ_SUBTITLE] 配置验证失败: {e}")

        if 'notification_email' in config_data and config_data['notification_email']:
            try:
                from ..config.settings import NotificationEmailConfig
                ne_data = dict(config_data['notification_email'])
                if 'password' not in ne_data or ne_data.get('password') == '********':
                    current_cfg = get_config()
                    current_password = current_cfg.notification_email.password
                    ne_data['password'] = (
                        _read_notification_email_password_from_disk()
                        or (current_password if current_password != '********' else '')
                    )
                ne_cfg = NotificationEmailConfig(**ne_data)
                config_data['notification_email'] = ne_cfg.model_dump()
            except Exception as e:
                logger.error(f"[NOTIFICATION] notification_email 配置验证失败: {e}")

        if 'notification_center' in config_data and config_data['notification_center']:
            try:
                from ..config.settings import NotificationCenterConfig
                nc_cfg = NotificationCenterConfig(**config_data['notification_center'])
                config_data['notification_center'] = nc_cfg.model_dump()
            except Exception as e:
                logger.error(f"[NOTIFICATION] notification_center 配置验证失败: {e}")

        result = save_config(config_data)
        logger.info(f"配置已保存，分类规则数: {len(config_data.get('classification', []))}")

        if 'kikoeru_server' in config_data:
            try:
                kikoeru_service = get_kikoeru_service()
                kikoeru_service.config = kikoeru_service._load_config()
                kikoeru_service.clear_cache()
                logger.info(
                    "[KIKOERU] 运行时配置已刷新: enabled=%s, server_url=%s",
                    kikoeru_service.config.enabled,
                    kikoeru_service.config.server_url,
                )
            except Exception:
                logger.warning("[KIKOERU] 刷新运行时配置失败", exc_info=True)

        # 重新读取配置文件确保数据已写入
        from ..config.settings import get_config
        current_config = get_config()
        get_task_engine()
        logger.info(f"当前配置中的分类规则: {[r.dict() for r in current_config.classification]}")

        # 如果密码清理配置变更，重启清理服务
        if 'password_cleanup' in config_data:
            logger.info("密码清理配置已变更，重启清理服务...")
            cleanup_service = get_cleanup_service()
            await cleanup_service.restart()
            logger.info("密码清理服务已重启")

        # 如果已处理压缩包清理配置变更，重启清理服务
        if 'processed_archive_cleanup' in config_data:
            logger.info("已处理压缩包清理配置已变更，重启清理服务...")
            archive_cleanup_service = get_processed_archive_cleanup_service()
            await archive_cleanup_service.restart()
            logger.info("已处理压缩包清理服务已重启")

        return {"message": "配置已保存", "config": config_data}
    except Exception as e:
        logger.error(f"保存配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")

@app.post("/api/config/reload")
async def reload_configuration():
    """重新加载配置文件（从磁盘重新读取）"""
    from ..config.settings import reload_config, get_config_file_path
    import os
    
    try:
        config_file_path = get_config_file_path()
        logger.info(f"[CONFIG RELOAD] 重新加载配置文件：{config_file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(config_file_path):
            logger.warning(f"[CONFIG RELOAD] 配置文件不存在：{config_file_path}")
            raise HTTPException(status_code=404, detail=f"配置文件不存在：{config_file_path}")
        
        # 重新加载配置
        new_config = reload_config()
        get_task_engine()
        
        logger.info(f"[CONFIG RELOAD] 配置重新加载成功")
        logger.info(f"[CONFIG RELOAD] storage.input_path = {new_config.storage.input_path}")
        logger.info(f"[CONFIG RELOAD] rename.template = '{new_config.rename.template}'")
        
        return {
            "message": "配置重新加载成功",
            "config_file": config_file_path,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新加载配置失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新加载配置失败：{str(e)}")


@app.get("/api/library-backup/status")
async def get_library_backup_status():
    service = get_backup_zip_service()
    return service.get_status()


@app.post("/api/library-backup/start")
async def start_library_backup():
    service = get_backup_zip_service()
    try:
        return await service.start()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动库存打包失败: {str(e)}")


@app.post("/api/library-backup/cancel")
async def cancel_library_backup():
    service = get_backup_zip_service()
    return await service.cancel()


@app.post("/api/library-backup/resume")
async def resume_library_backup():
    """从断点恢复库存打包任务"""
    service = get_backup_zip_service()
    try:
        return await service.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复库存打包失败: {str(e)}")


@app.get("/api/library-backup/checkpoint")
async def get_library_backup_checkpoint():
    """获取库存打包断点信息"""
    service = get_backup_zip_service()
    checkpoint = service.get_checkpoint_info()
    return checkpoint or {"has_checkpoint": False}


@app.post("/api/watcher/start")
async def start_watcher():
    """启动文件夹监视器"""
    watcher = get_watcher()
    watcher.start()
    return {"message": "监视器已启动"}

@app.post("/api/watcher/stop")
async def stop_watcher():
    """停止文件夹监视器"""
    watcher = get_watcher()
    watcher.stop()
    return {"message": "监视器已停止"}

@app.get("/api/watcher/status")
async def get_watcher_status():
    """获取监视器状态"""
    watcher = get_watcher()
    return {
        "is_running": watcher.is_running,
        "watch_path": get_config().storage.input_path,
        "pending_files": list(watcher.pending_files)
    }

@app.post("/api/scan")
async def scan_input_directory():
    """手动扫描输入目录"""
    result = await _scan_and_create_tasks(
        source_page="dashboard",
        source_action="scan_input",
        source_label="仪表盘 / 扫描导入",
    )
    return {
        "message": f"扫描完成，找到 {result['found_count']} 个文件",
        "found_count": result["found_count"],
        "task_ids": result["task_ids"],
        "batch_id": result.get("batch_id"),
    }

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ========== 密码库管理 API ==========

class PasswordEntryCreate(BaseModel):
    """创建密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: str
    description: Optional[str] = None
    source: str = "manual"

class PasswordEntryUpdate(BaseModel):
    """更新密码请求模型"""
    rjcode: Optional[str] = None
    filename: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None

class PasswordEntryResponse(BaseModel):
    """密码响应模型"""
    id: str
    rjcode: Optional[str]
    filename: Optional[str]
    password: str
    description: Optional[str]
    source: str
    use_count: int
    last_used_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

class PasswordListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PasswordEntryResponse]


class ConflictRetryRequest(BaseModel):
    password: Optional[str] = None

@app.get("/api/passwords", response_model=PasswordListResponse)
async def get_passwords(
    rjcode: Optional[str] = None,
    filename: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20
):
    """获取密码列表，支持筛选和排序
    
    Args:
        rjcode: 按RJ号筛选
        filename: 按文件名筛选
        search: 搜索关键词
        sort_by: 排序字段（created_at, updated_at, rjcode, filename, use_count）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        query = db.query(PasswordEntry)
        
        if rjcode:
            query = query.filter(PasswordEntry.rjcode == rjcode)
        if filename:
            query = query.filter(PasswordEntry.filename.contains(filename))
        if search:
            query = query.filter(
                (PasswordEntry.rjcode.contains(search)) |
                (PasswordEntry.filename.contains(search)) |
                (PasswordEntry.password.contains(search)) |
                (PasswordEntry.description.contains(search))
            )
        
        # 排序功能
        valid_sort_fields = {
            "created_at": PasswordEntry.created_at,
            "updated_at": PasswordEntry.updated_at,
            "rjcode": PasswordEntry.rjcode,
            "filename": PasswordEntry.filename,
            "use_count": PasswordEntry.use_count
        }
        
        # 设置默认排序字段
        sort_field_key = sort_by if sort_by else "created_at"
        sort_field = valid_sort_fields.get(sort_field_key, PasswordEntry.created_at)
        
        # 设置默认排序方向
        order = sort_order.lower() if sort_order else "desc"
        if order == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 200)
        total = query.order_by(None).count()
        passwords = query.offset((safe_page - 1) * safe_page_size).limit(safe_page_size).all()
        return PasswordListResponse(
            total=total,
            page=safe_page,
            page_size=safe_page_size,
            items=[PasswordEntryResponse(**p.to_dict()) for p in passwords]
        )
    finally:
        db.close()

@app.post("/api/passwords", response_model=PasswordEntryResponse)
async def create_password(entry: PasswordEntryCreate):
    """创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    try:
        normalized_rjcode = normalize_rjcode_value(entry.rjcode)
        normalized_filename = normalize_filename_value(entry.filename)
        normalized_password = normalize_password_value(entry.password)
        normalized_description = normalize_optional_text(entry.description)

        # 记录接收到的数据（用于调试）
        logger.info(
            f"创建密码条目 - RJ={normalized_rjcode}, File={normalized_filename}, "
            f"Password长度={len(normalized_password) if normalized_password else 0}"
        )
        
        # 确保密码不为空
        if not normalized_password:
            raise HTTPException(status_code=400, detail="密码不能为空")
        
        # 检查是否已存在相同RJ号或文件名的密码
        existing = None
        if normalized_rjcode:
            existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
        if not existing and normalized_filename:
            existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
        
        if existing:
            # 更新现有密码
            existing.rjcode = normalized_rjcode
            existing.filename = normalized_filename
            existing.password = normalized_password
            existing.description = normalized_description if entry.description is not None else existing.description
            existing.updated_at = datetime.now()
            db.commit()
            logger.info(f"更新密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
            return PasswordEntryResponse(**existing.to_dict())
        
        # 创建新密码条目
        new_entry = PasswordEntry(
            id=str(uuid.uuid4()),
            rjcode=normalized_rjcode,
            filename=normalized_filename,
            password=normalized_password,
            description=normalized_description,
            source=entry.source
        )
        db.add(new_entry)
        db.commit()
        logger.info(f"创建密码成功: RJ={normalized_rjcode}, File={normalized_filename}")
        return PasswordEntryResponse(**new_entry.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建密码条目失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存密码失败: {str(e)}")
    finally:
        db.close()

@app.post("/api/passwords/batch")
async def batch_create_passwords(entries: List[PasswordEntryCreate]):
    """批量创建密码条目"""
    from ..models.database import PasswordEntry, get_db
    from sqlalchemy import func
    import uuid
    
    db = next(get_db())
    created_count = 0
    updated_count = 0
    
    try:
        for entry in entries:
            normalized_rjcode = normalize_rjcode_value(entry.rjcode)
            normalized_filename = normalize_filename_value(entry.filename)
            normalized_password = normalize_password_value(entry.password)
            normalized_description = normalize_optional_text(entry.description)

            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")

            # 检查是否已存在
            existing = None
            if normalized_rjcode:
                existing = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode) == normalized_rjcode).first()
            if not existing and normalized_filename:
                existing = db.query(PasswordEntry).filter(PasswordEntry.filename == normalized_filename).first()
            
            if existing:
                # 更新
                existing.rjcode = normalized_rjcode
                existing.filename = normalized_filename
                existing.password = normalized_password
                existing.description = normalized_description if entry.description is not None else existing.description
                existing.updated_at = datetime.now()
                updated_count += 1
            else:
                # 创建新条目
                new_entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    rjcode=normalized_rjcode,
                    filename=normalized_filename,
                    password=normalized_password,
                    description=normalized_description,
                    source=entry.source
                )
                db.add(new_entry)
                created_count += 1
        
        db.commit()
        logger.info(f"批量导入密码: 新建 {created_count} 条, 更新 {updated_count} 条")
        return {
            "message": f"批量导入完成",
            "created": created_count,
            "updated": updated_count
        }
    except Exception as e:
        db.rollback()
        logger.error(f"批量导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量导入失败: {str(e)}")
    finally:
        db.close()

@app.put("/api/passwords/{password_id}", response_model=PasswordEntryResponse)
async def update_password(password_id: str, entry: PasswordEntryUpdate):
    """更新密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")

        provided_fields = getattr(entry, "model_fields_set", None)
        if provided_fields is None:
            provided_fields = getattr(entry, "__fields_set__", set())

        if "rjcode" in provided_fields:
            password_entry.rjcode = normalize_rjcode_value(entry.rjcode)
        if "filename" in provided_fields:
            password_entry.filename = normalize_filename_value(entry.filename)
        if "password" in provided_fields:
            normalized_password = normalize_password_value(entry.password)
            if not normalized_password:
                raise HTTPException(status_code=400, detail="密码不能为空")
            password_entry.password = normalized_password
        if "description" in provided_fields:
            password_entry.description = normalize_optional_text(entry.description)
        
        password_entry.updated_at = datetime.now()
        db.commit()
        
        return PasswordEntryResponse(**password_entry.to_dict())
    finally:
        db.close()

@app.delete("/api/passwords/{password_id}")
async def delete_password(password_id: str):
    """删除密码条目"""
    from ..models.database import PasswordEntry, get_db
    
    db = next(get_db())
    try:
        password_entry = db.query(PasswordEntry).filter(PasswordEntry.id == password_id).first()
        if not password_entry:
            raise HTTPException(status_code=404, detail="密码条目不存在")
        
        db.delete(password_entry)
        db.commit()
        return {"message": "密码已删除"}
    finally:
        db.close()

@app.get("/api/passwords/find-for-archive")
async def find_password_for_archive(archive_path: str):
    """查找适合指定压缩包的密码"""
    from ..models.database import PasswordEntry, get_db
    from pathlib import Path
    import re
    
    db = next(get_db())
    try:
        filename = Path(archive_path).name
        
        # 提取RJ号
        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
        rjcode = rj_match.group(0).upper() if rj_match else None
        
        # 首先尝试精确匹配RJ号
        if rjcode:
            entry = db.query(PasswordEntry).filter(PasswordEntry.rjcode == rjcode).first()
            if entry:
                return {
                    "found": True,
                    "password": normalize_password_value(entry.password),
                    "match_type": "rjcode",
                    "rjcode": rjcode,
                    "entry": entry.to_dict()
                }
        
        # 其次尝试文件名匹配
        entry = db.query(PasswordEntry).filter(PasswordEntry.filename == filename).first()
        if entry:
            return {
                "found": True,
                "password": normalize_password_value(entry.password),
                "match_type": "filename",
                "entry": entry.to_dict()
            }
        
        return {"found": False, "rjcode": rjcode}
    finally:
        db.close()

@app.post("/api/passwords/import-from-text")
async def import_passwords_from_text(request: Request):
    """从文本批量导入密码 - 每行一个密码，只添加密码不解析RJ号
    
    格式：每行一个密码，系统自动尝试匹配
    """
    from ..models.database import PasswordEntry, get_db
    import uuid
    
    data = await request.json()
    text = data.get("text", "")
    
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    
    db = next(get_db())
    entries = []
    lines = text.strip().split('\n')
    
    try:
        for line in lines:
            password = normalize_password_value(line)
            if not password:
                continue
            
            # 检查该密码是否已存在（避免重复）
            existing = db.query(PasswordEntry).filter(PasswordEntry.password == password).first()
            if existing:
                # 密码已存在，跳过
                entries.append({"password": password, "status": "skipped", "reason": "已存在"})
            else:
                # 创建新的密码条目（只存储密码，不关联RJ号或文件名）
                entry = PasswordEntry(
                    id=str(uuid.uuid4()),
                    password=password,
                    source='batch',
                    description='批量导入'
                )
                db.add(entry)
                entries.append({"password": password, "status": "success"})
        
        db.commit()
        success_count = sum(1 for e in entries if e["status"] == "success")
        skipped_count = sum(1 for e in entries if e["status"] == "skipped")
        
        return {
            "message": f"导入完成：新建 {success_count} 个，跳过 {skipped_count} 个（已存在）",
            "imported": success_count,
            "skipped": skipped_count,
            "entries": entries
        }
    except Exception as e:
        db.rollback()
        logger.error(f"导入密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
    finally:
        db.close()

@app.get("/api/logs")
async def get_logs(lines: int = 100, since_offset: int = -1):
    """获取日志文件内容。

    - ``since_offset=-1``：全量模式，返回末尾 lines 条日志及当前文件字节偏移量。
    - ``since_offset>=0``：增量模式，仅返回该字节偏移后的新内容（文件未轮转时）。
      若文件已轮转（size < since_offset），自动退回全量模式。
    响应格式：``{ "logs": [...], "next_offset": N, "is_full": bool }``
    """
    import os
    log_dir = os.environ.get('DATA_PATH', './data')
    log_files = [
        os.path.join(log_dir, 'app.log'),
        os.path.join(log_dir, 'desktop_app.log'),
    ]
    log_file = next((path for path in log_files if os.path.exists(path)), None)
    if not log_file:
        return {"logs": [], "next_offset": 0, "is_full": True}

    try:
        line_limit = max(50, min(int(lines or 100), 5000))
        _log_file = log_file

        def _read_log():
            file_size = os.path.getsize(_log_file)
            with open(_log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # 增量模式：文件未轮转且有新内容
                if 0 <= since_offset <= file_size:
                    if since_offset == file_size:
                        return {"logs": [], "next_offset": file_size, "is_full": False}
                    f.seek(since_offset)
                    new_lines = [l.strip() for l in f.read().splitlines() if l.strip()]
                    return {"logs": new_lines, "next_offset": file_size, "is_full": False}

            # 全量模式：首次请求或文件已轮转
            # 使用二进制反向块读取，仅扫描文件尾部，避免超大日志全文件遍历。
            def _tail_lines(path: str, n: int):
                if n <= 0:
                    return []
                chunk_size = 64 * 1024
                data = b''
                with open(path, 'rb') as bf:
                    bf.seek(0, os.SEEK_END)
                    pos = bf.tell()
                    lines_found = 0
                    while pos > 0 and lines_found <= n * 2:
                        read_size = chunk_size if pos >= chunk_size else pos
                        pos -= read_size
                        bf.seek(pos)
                        block = bf.read(read_size)
                        data = block + data
                        lines_found = data.count(b'\n')
                        if lines_found >= n + 1:
                            break
                text = data.decode('utf-8', errors='ignore')
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                return lines[-n:]

            result = _tail_lines(_log_file, line_limit)
            return {"logs": result, "next_offset": file_size, "is_full": True}

        return await asyncio.to_thread(_read_log)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")

@app.get("/api/logs/search")
async def search_logs(
    q: str = '',
    levels: str = '',
    limit: int = 500,
    cursor: int = 0,
    max_scan_mb: int = 8,
):
    """在日志尾部扫描窗口中全文检索，避免超大日志全文件扫描拖垮后端。

    - ``q``：关键词（大小写不敏感，空则不过滤）
    - ``levels``：逗号分隔的级别列表，如 ``INFO,ERROR``（空则不过滤）
        - ``limit``：单页返回条数（默认 500，上限 1000）
        - ``cursor``：匹配游标偏移（默认 0）
        响应格式：
            ``{ "logs": [...], "total_matched": N, "next_cursor": M, "has_more": bool }``
    """
    import os, re as _re
    log_dir = os.environ.get('DATA_PATH', './data')
    log_files = [
        os.path.join(log_dir, 'app.log'),
        os.path.join(log_dir, 'desktop_app.log'),
    ]
    log_file = next((path for path in log_files if os.path.exists(path)), None)
    if not log_file:
        return {"logs": [], "total_matched": 0, "next_cursor": 0, "has_more": False}

    try:
        max_limit = max(50, min(int(limit or 500), 1000))
        safe_cursor = max(0, int(cursor or 0))
        kw = q.strip().lower() if q else ''
        lvl_set = {v.strip().upper() for v in levels.split(',') if v.strip()} if levels else set()
        scan_bytes = max(1024 * 1024, min(int(max_scan_mb or 8), 64) * 1024 * 1024)
        _log_file = log_file

        _lvl_re = _re.compile(
            r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]'
            r'|^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+-\s+\S+\s+-\s+(\w+)\s+-'
        )

        def _search():
            results = []
            matched_seen = 0
            has_more = False
            file_size = os.path.getsize(_log_file)
            start_offset = max(0, file_size - scan_bytes)
            with open(_log_file, 'rb') as f:
                f.seek(start_offset)
                if start_offset > 0:
                    f.readline()
                raw_data = f.read(scan_bytes)
            text = raw_data.decode('utf-8', errors='ignore')
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if lvl_set:
                    m = _lvl_re.match(line)
                    lvl = (m.group(2) or m.group(4) or '').upper() if m else 'INFO'
                    if lvl not in lvl_set:
                        continue
                if kw and kw not in line.lower():
                    continue
                matched_seen += 1
                if matched_seen <= safe_cursor:
                    continue
                if len(results) < max_limit:
                    results.append(line)
                else:
                    has_more = True
                    break
            next_cursor = safe_cursor + len(results)
            total_estimate = next_cursor + (1 if has_more else 0)
            return {
                "logs": results,
                "total_matched": total_estimate,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "total_is_estimate": True,
                "scan_bytes": min(file_size, scan_bytes),
            }

        return await asyncio.to_thread(_search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"日志检索失败: {str(e)}")

@app.get("/api/conflicts")
async def get_conflicts(include_stats: bool = False):
    """获取问题作品列表"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..core.task_engine import TaskStatus
    from ..models.database import ConflictWork, Task as TaskRecord, get_db

    def _normalize_conflict_metadata(raw_metadata):
        if isinstance(raw_metadata, dict):
            return dict(raw_metadata)
        if raw_metadata in (None, "", []):
            return {}
        if isinstance(raw_metadata, str):
            with contextlib.suppress(Exception):
                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    return parsed
            return {"raw_metadata": raw_metadata}
        if isinstance(raw_metadata, list):
            return {"raw_metadata": raw_metadata}
        with contextlib.suppress(Exception):
            return dict(raw_metadata)
        return {"raw_metadata": str(raw_metadata)}

    active_task_statuses = {
        TaskStatus.PENDING.value,
        TaskStatus.PROCESSING.value,
        TaskStatus.PAUSED.value,
        TaskStatus.WAITING_MANUAL.value,
        TaskStatus.WAITING_RETRY.value,
    }

    def _get_linked_task_status(task_id: Any) -> str:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return ""

        linked_task = engine.get_task(normalized_task_id)
        if linked_task is not None:
            linked_status = getattr(linked_task, "status", "")
            if isinstance(linked_status, TaskStatus):
                return linked_status.value
            return str(linked_status or "").strip().lower()

        db_task = db.query(TaskRecord.status).filter(TaskRecord.id == normalized_task_id).first()
        return str((db_task[0] if db_task else "") or "").strip().lower()

    def _backfill_failed_import_conflicts() -> None:
        """把历史漏写的问题导入任务补进问题作品列表。"""
        failed_rows = (
            db.query(TaskRecord)
            .filter(
                TaskRecord.status == "failed",
                TaskRecord.type.in_(["extract", "auto_process", "process_existing_folder"]),
            )
            .order_by(TaskRecord.completed_at.desc(), TaskRecord.created_at.desc())
            .limit(200)
            .all()
        )
        for task_row in failed_rows:
            source_path = str(task_row.source_path or "").strip()
            if not source_path:
                continue
            exists = (
                db.query(ConflictWork.id)
                .filter(
                    ConflictWork.conflict_type.in_(["EXTRACT_FAILED", "PROCESS_FAILED"]),
                    or_(
                        ConflictWork.task_id == task_row.id,
                        ConflictWork.new_path == source_path,
                    ),
                    ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                )
                .first()
            )
            if exists:
                continue

            metadata = _normalize_conflict_metadata(task_row.task_metadata)
            reason = str(task_row.error_message or metadata.get("error_message") or task_row.current_step or "任务失败").strip()
            step = str(task_row.current_step or "").strip()
            combined = f"{step} {reason}".lower()
            is_extract_failure = (
                str(task_row.type or "") == "extract"
                or any(keyword in combined for keyword in ["解压", "密码", "压缩包"])
            )
            rjcode = (
                normalize_rjcode_value(metadata.get("rjcode"))
                or normalize_rjcode_value(metadata.get("inferred_rjcode"))
                or normalize_rjcode_value(source_path)
            )
            failure_metadata = {
                **metadata,
                "failure_stage": "extract" if is_extract_failure else "process",
                "error_message": reason,
                "available_actions": ["RETRY", "SKIP"],
                "source_task_type": str(task_row.type or "auto_process"),
                "failed_task_id": task_row.id,
                "failed_step": step,
                "failed_progress": int(task_row.progress or 0),
                "backfilled_from_failed_task": True,
                "source_missing": not os.path.exists(source_path),
            }
            db.add(ConflictWork(
                id=str(uuid.uuid4()),
                task_id=task_row.id,
                rjcode=rjcode or None,
                conflict_type="EXTRACT_FAILED" if is_extract_failure else "PROCESS_FAILED",
                existing_path="",
                new_path=source_path,
                new_metadata=failure_metadata,
                status="PENDING",
                linked_works_info=[],
                analysis_info={},
                related_rjcodes=[],
                created_at=datetime.now(),
            ))
        db.commit()

    db = next(get_db())
    try:
        resolution_service = get_conflict_resolution_service()
        engine = get_task_engine()
        _backfill_failed_import_conflicts()
        conflicts = db.query(ConflictWork).filter(
            ConflictWork.status.in_(["PENDING", "PROCESSING"]),
            ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
        ).all()

        # ---- 第一阶段：串行处理 DB 写入（状态恢复）和纯计算字段 ----
        # SQLAlchemy session 不能并发使用，所以这一段保持串行。
        per_conflict_actions: list[list[str]] = []
        for conflict in conflicts:
            try:
                conflict.new_metadata = _normalize_conflict_metadata(conflict.new_metadata)
                normalized_status = str(conflict.status or "").strip().upper()
                if normalized_status == "PROCESSING":
                    _nm = _normalize_conflict_metadata(conflict.new_metadata)
                    _recovery_task_id = str((_nm.get("resolution_task_id") or conflict.task_id or "")).strip()
                    linked_task_status = _get_linked_task_status(_recovery_task_id)
                    if linked_task_status not in active_task_statuses:
                        conflict.status = "PENDING"
                        next_metadata = _normalize_conflict_metadata(conflict.new_metadata)
                        next_metadata["resolution_task_state"] = "stale_processing_recovered"
                        next_metadata["resolution_recovered_at"] = datetime.now().isoformat()
                        conflict.new_metadata = next_metadata
                        db.commit()
            except Exception as exc:
                logger.error(
                    "恢复问题作品状态失败 conflict_id=%s task_id=%s error=%s",
                    getattr(conflict, "id", None),
                    getattr(conflict, "task_id", None),
                    exc,
                    exc_info=True,
                )
                db.rollback()
                conflict.new_metadata = _normalize_conflict_metadata(getattr(conflict, "new_metadata", None))

            try:
                actions = resolution_service.get_available_actions(conflict)
            except Exception as exc:
                logger.error(
                    "计算问题作品可用操作失败 conflict_id=%s error=%s",
                    getattr(conflict, "id", None),
                    exc,
                    exc_info=True,
                )
                actions = ["SKIP"]
            per_conflict_actions.append(actions)

        # ---- 第二阶段：并行计算 conflict 上下文（远程 stat 是 IO 密集，并发能显著降低串行延迟） ----
        # 用信号量限制群晖并发，避免对 NAS 造成压力或触发限流。
        gather_semaphore = asyncio.Semaphore(8)

        async def _build_context(conflict_obj):
            async with gather_semaphore:
                try:
                    return await resolution_service.describe_conflict_async(
                        conflict_obj, include_stats=include_stats,
                    )
                except Exception as exc:
                    logger.error(
                        "构建问题作品上下文失败 conflict_id=%s error=%s",
                        getattr(conflict_obj, "id", None),
                        exc,
                        exc_info=True,
                    )
                    return {
                        "existing": {
                            "library_id": None,
                            "library_type": "local",
                            "library_name": "",
                            "path": str(conflict_obj.existing_path or "").strip(),
                            "is_remote": False,
                            "stats": None,
                        },
                        "source": {
                            "library_id": None,
                            "library_type": "local",
                            "library_name": "",
                            "path": str(conflict_obj.new_path or "").strip(),
                            "is_remote": False,
                            "stats": None,
                        },
                        "new_path_kind": "archive" if os.path.isfile(str(conflict_obj.new_path or "")) else "folder",
                        "metadata": _normalize_conflict_metadata(conflict_obj.new_metadata),
                        "context_error": str(exc),
                    }

        contexts = await asyncio.gather(*(_build_context(c) for c in conflicts)) if conflicts else []

        # ---- 第三阶段：装配响应 ----
        conflict_items = []
        for index, conflict in enumerate(conflicts):
            available_actions = per_conflict_actions[index]
            context = contexts[index]

            linked_task_info = None
            linked_task_id = str(
                (_normalize_conflict_metadata(conflict.new_metadata).get("resolution_task_id") or conflict.task_id or "")
            ).strip()
            if linked_task_id:
                linked_task = engine.get_task(linked_task_id)
                if linked_task is not None:
                    linked_task_info = {
                        "id": linked_task.id,
                        "status": linked_task.status.value if isinstance(linked_task.status, TaskStatus) else str(linked_task.status or ""),
                        "progress": int(getattr(linked_task, "progress", 0) or 0),
                        "current_step": str(getattr(linked_task, "current_step", "") or ""),
                        "error_message": str(getattr(linked_task, "error_message", "") or ""),
                    }

            conflict_items.append(
                {
                    "id": conflict.id,
                    "task_id": conflict.task_id,
                    "rjcode": conflict.rjcode,
                    "conflict_type": conflict.conflict_type,
                    "existing_path": conflict.existing_path,
                    "new_path": conflict.new_path,
                    "new_metadata": _normalize_conflict_metadata(conflict.new_metadata),
                    "status": conflict.status,
                    "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
                    "available_actions": available_actions,
                    "linked_task": linked_task_info,
                    "context": context,
                }
            )
        return {
            "conflicts": conflict_items
        }
    except Exception as exc:
        logger.error("获取问题作品列表失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取问题作品失败: {str(exc)}")
    finally:
        db.close()

@app.get("/api/conflicts/count")
def get_conflicts_count(db: Session = Depends(get_db)):
    """获取问题作品数量（轻量接口，供首页轮询使用）。"""
    from ..models.database import ConflictWork

    try:
        total = (
            db.query(func.count(ConflictWork.id))
            .filter(
                ConflictWork.status.in_(["PENDING", "PROCESSING"]),
                ConflictWork.conflict_type != "LINKED_SUBTITLE_IMPORT",
            )
            .scalar()
        )
        return {"count": int(total or 0)}
    except Exception as exc:
        logger.error("获取问题作品数量失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取问题作品数量失败: {exc}")

@app.post("/api/conflicts/{conflict_id}/retry")
async def retry_extract_failed_conflict(conflict_id: str, payload: Optional[ConflictRetryRequest] = None):
    """重试问题作品中的失败项。"""
    from ..models.database import ConflictWork, get_db
    from ..core.task_engine import TaskStatus

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")
        if conflict.status != "PENDING":
            raise HTTPException(status_code=400, detail="当前问题项已不是待处理状态")
        if conflict.conflict_type not in {"EXTRACT_FAILED", "PROCESS_FAILED"}:
            raise HTTPException(status_code=400, detail="只有失败问题项支持重试")

        source_path = str(conflict.new_path or "").strip()
        if not source_path:
            raise HTTPException(status_code=400, detail="缺少待重试的源路径")
        if not os.path.exists(source_path):
            raise HTTPException(status_code=404, detail="待重试的源文件不存在")

        specified_password = normalize_password_value(payload.password if payload else None)

        engine = get_task_engine()
        normalized_source_path = os.path.normcase(os.path.normpath(source_path))
        existing_task = next(
            (
                task for task in engine.get_all_tasks()
                if os.path.normcase(os.path.normpath(str(task.source_path or ""))) == normalized_source_path
                and task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.PAUSED}
            ),
            None,
        )
        if existing_task:
            existing_metadata = existing_task.task_metadata or {}
            existing_manual_password = normalize_password_value(existing_metadata.get("manual_retry_password"))
            if specified_password and existing_manual_password != specified_password:
                if existing_task.status == TaskStatus.PROCESSING:
                    raise HTTPException(
                        status_code=409,
                        detail="同源任务已经开始解压，不能把指定密码热替换到正在运行的 7z 进程；请取消或等待本次失败后再重试",
                    )
                if existing_task.status != TaskStatus.PENDING:
                    raise HTTPException(
                        status_code=409,
                        detail="同源任务已存在但不是可注入密码的等待态，请等待当前任务结束后再用指定密码重试",
                    )
            conflict.status = "PROCESSING"
            conflict.task_id = existing_task.id
            next_metadata = dict(conflict.new_metadata or {})
            next_metadata["resolution_task_state"] = "running"
            next_metadata["resolution_action"] = "RETRY"
            next_metadata["resolution_requested_at"] = datetime.now().isoformat()
            next_metadata["resolution_task_id"] = existing_task.id
            conflict.new_metadata = next_metadata
            existing_task.task_metadata["retry_conflict_id"] = conflict.id
            existing_task.task_metadata["retry_conflict_source_path"] = source_path
            existing_task.task_metadata["retry_conflict_type"] = conflict.conflict_type
            existing_task.task_metadata["retry_from_conflicts"] = True
            existing_task.task_metadata["conflict_resolution_conflict_id"] = conflict.id
            existing_task.task_metadata["conflict_resolution_action"] = "RETRY"
            if conflict.conflict_type == "EXTRACT_FAILED":
                existing_task.task_metadata["skip_retry_precheck"] = True
            if specified_password:
                existing_task.task_metadata["manual_retry_password"] = specified_password
                existing_task.task_metadata["manual_retry_password_only"] = True
                existing_task.task_metadata["manual_retry_password_requested"] = True
            if conflict.task_id:
                existing_task.task_metadata["retry_failed_task_id"] = str(conflict.task_id)
            db.commit()
            return {
                "success": True,
                "message": "已存在同源重试任务，继续跟踪当前任务",
                "task_id": existing_task.id,
                "already_running": True,
            }

        source_task_type = str((conflict.new_metadata or {}).get("source_task_type") or TaskType.AUTO_PROCESS.value).strip()
        retry_task_type = TaskType(source_task_type) if source_task_type in {task_type.value for task_type in TaskType} else TaskType.AUTO_PROCESS

        if conflict.task_id:
            engine.cleanup_retry_output_artifacts(str(conflict.task_id), source_path)

        task = Task(
            task_type=retry_task_type,
            source_path=source_path,
            auto_classify=True,
        )
        task.task_metadata["retry_conflict_id"] = conflict.id
        task.task_metadata["retry_conflict_source_path"] = source_path
        task.task_metadata["retry_conflict_type"] = conflict.conflict_type
        task.task_metadata["retry_from_conflicts"] = True
        if conflict.conflict_type == "EXTRACT_FAILED":
            task.task_metadata["skip_retry_precheck"] = True
        task.task_metadata["conflict_resolution_conflict_id"] = conflict.id
        task.task_metadata["conflict_resolution_action"] = "RETRY"
        if specified_password:
            task.task_metadata["manual_retry_password"] = specified_password
            task.task_metadata["manual_retry_password_only"] = True
            task.task_metadata["manual_retry_password_requested"] = True
        if conflict.task_id:
            task.task_metadata["retry_failed_task_id"] = str(conflict.task_id)
        if conflict.rjcode:
            task.task_metadata["inferred_rjcode"] = conflict.rjcode

        conflict.status = "PROCESSING"
        next_metadata = dict(conflict.new_metadata or {})
        next_metadata["resolution_task_state"] = "queued"
        next_metadata["resolution_action"] = "RETRY"
        next_metadata["resolution_requested_at"] = datetime.now().isoformat()
        conflict.new_metadata = next_metadata
        await engine.submit(task)
        conflict.task_id = task.id
        conflict.new_metadata = {
            **dict(conflict.new_metadata or {}),
            "resolution_task_id": task.id,
        }
        db.commit()
        return {
            "success": True,
            "message": "已开始使用指定密码重试失败问题项" if specified_password else "已开始重试失败问题项",
            "task_id": task.id,
            "already_running": False,
        }
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/preview")
async def preview_conflict_resolution(conflict_id: str, payload: dict):
    """生成问题作品处理预览"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..models.database import ConflictWork, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action = service.normalize_action(payload.get("action"))
        if action not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")

        if action == "KEEP_NEW":
            preview = await service.get_delete_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                "preview": preview,
            }

        if action == "MERGE":
            merge_preview = await service.create_merge_preview(conflict)
            return {
                "action": action,
                "conflict_id": conflict.id,
                **merge_preview,
            }

        raise HTTPException(status_code=400, detail="当前动作不需要预览")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("生成问题作品预览失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成处理预览失败: {exc}")
    finally:
        db.close()

@app.post("/api/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, action: dict):
    """处理问题作品"""
    from ..core.conflict_resolution_service import get_conflict_resolution_service
    from ..core.task_engine import Task, TaskStatus, TaskType, get_task_engine
    from ..models.database import ConflictWork, ProcessedArchive, get_db

    db = next(get_db())
    try:
        conflict = db.query(ConflictWork).filter(ConflictWork.id == conflict_id).first()
        if not conflict:
            raise HTTPException(status_code=404, detail="问题作品不存在")

        service = get_conflict_resolution_service()
        action_type = service.normalize_action(action.get("action"))
        if action_type not in service.get_available_actions(conflict):
            raise HTTPException(status_code=400, detail="当前问题项不支持该操作")
        confirmed = bool(action.get("confirmed"))
        engine = get_task_engine()

        try:
            if action_type == "KEEP_NEW":
                if not confirmed:
                    raise HTTPException(status_code=400, detail="保留新版前必须先完成删除审查确认")
                source_path = str(conflict.new_path or "").strip()
                existing_path = str(conflict.existing_path or "").strip()
                if not source_path:
                    raise HTTPException(status_code=400, detail="缺少待处理源路径")
                if not existing_path:
                    raise HTTPException(status_code=400, detail="缺少待替换目标路径")
                if not os.path.exists(source_path):
                    raise HTTPException(status_code=404, detail="待处理源文件不存在")

                existing_task = None
                if conflict.task_id:
                    existing_task = engine.get_task(str(conflict.task_id))
                if existing_task and existing_task.status == TaskStatus.PROCESSING:
                    return {
                        "success": True,
                        "conflict_id": conflict.id,
                        "action": action_type,
                        "task_id": existing_task.id,
                        "already_running": True,
                        "message": "保留新版任务已在执行中",
                    }

                conflict.status = "PROCESSING"
                next_metadata = dict(conflict.new_metadata or {})
                next_metadata["resolution_task_state"] = "queued"
                next_metadata["resolution_action"] = action_type
                next_metadata["resolution_requested_at"] = datetime.now().isoformat()
                conflict.new_metadata = next_metadata

                task_type = TaskType.AUTO_PROCESS if os.path.isfile(source_path) else TaskType.PROCESS_EXISTING_FOLDER
                task = Task(
                    task_type=task_type,
                    source_path=source_path,
                    auto_classify=True,
                    metadata={
                        **next_metadata,
                        "existing_folder_resolution": "KEEP_NEW",
                        "existing_path": existing_path,
                        "conflict_resolution_conflict_id": conflict.id,
                        "conflict_resolution_action": "KEEP_NEW",
                        "source_page": "conflicts",
                        "source_action": "keep_new",
                        "source_label": conflict.rjcode or os.path.basename(source_path),
                        "business_key": conflict.rjcode or conflict.id,
                        "target_library_id": next_metadata.get("existing_library_id") or next_metadata.get("target_library_id") or "",
                    },
                    rjcode=conflict.rjcode or None,
                )
                if conflict.task_id:
                    task.task_metadata["parent_conflict_task_id"] = str(conflict.task_id)
                await engine.submit(task)
                conflict.task_id = task.id
                db.commit()
                return {
                    "success": True,
                    "conflict_id": conflict.id,
                    "action": action_type,
                    "task_id": task.id,
                    "already_running": False,
                    "message": "已提交保留新版后台任务，任务状态已切换为解压中",
                }
            elif action_type == "MERGE":
                previous_conflict_status = str(conflict.status or "PENDING").strip() or "PENDING"
                previous_task_status = None
                previous_task_step = None
                conflict_task = None
                if conflict.task_id:
                    conflict_task = engine.get_task(str(conflict.task_id))
                    if conflict_task:
                        previous_task_status = conflict_task.status
                        previous_task_step = conflict_task.current_step
                conflict.status = "PROCESSING"
                if conflict_task:
                    conflict_task.status = TaskStatus.PROCESSING
                    conflict_task.started_at = conflict_task.started_at or datetime.now()
                    conflict_task.update_progress(max(int(conflict_task.progress or 0), 10), "合并中")
                db.commit()
                result = await service.resolve_merge(
                    conflict,
                    action.get("merge_session_id"),
                    action.get("merge_decisions") or {},
                )
                conflict.status = action_type
                if conflict_task:
                    conflict_task.update_progress(100, "合并完成")
                    conflict_task.complete()
            else:
                result = await service.resolve_skip(conflict)
                conflict.status = action_type
                if conflict.task_id:
                    engine.update_task_status(str(conflict.task_id), TaskStatus.COMPLETED, "跳过完成")
        except Exception:
            if action_type == "MERGE":
                conflict.status = previous_conflict_status
                if conflict_task and previous_task_status:
                    conflict_task.status = previous_task_status
                    if previous_task_step:
                        conflict_task.current_step = previous_task_step
            db.commit()
            raise

        if conflict.new_path:
            archive_record = db.query(ProcessedArchive).filter(
                ProcessedArchive.filename == os.path.basename(str(conflict.new_path))
            ).first()
            if archive_record:
                archive_record.status = "completed"
                archive_record.processed_at = datetime.now()

        db.commit()
        return {
            "success": True,
            "conflict_id": conflict.id,
            "action": action_type,
            **result,
        }
        
        # 检查new_path是否是压缩包（预检阶段的冲突）
        from ..core.watcher import ArchiveHandler
        temp_handler = ArchiveHandler(lambda x: None, lambda: set(), lambda: False, lambda x: None)
        is_archive = temp_handler._is_archive(conflict.new_path)
        
        if action_type == "KEEP_NEW":
            if os.path.exists(conflict.existing_path):
                shutil.rmtree(conflict.existing_path)
            
            if is_archive:
                logger.info(f"保留新版：先解压压缩包 {conflict.new_path}")
                
                is_in_processed = conflict.new_path.startswith(config.storage.processed_archives_path)
                if is_in_processed:
                    logger.info(f"检测到文件已在 processed 目录中，设置 skip_archive=True: {conflict.new_path}")
                
                # 检查冲突前先确认没有正在执行同RJ编号的操作
                engine = get_task_engine()
                rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path)) 
                
                skip_archive_bool = bool(conflict.new_path.startswith(config.storage.processed_archives_path)) 
                
                # 如果正在处理同样的RJ号，优先复用正在处理的同RJ号的任务
                if rjcode_of_new_path and engine.is_rjcode_processing(rjcode_of_new_path):
                    # 查找正在处理同RJ号的任务
                    existing_tasks_for_rj = [t for t in engine.get_all_tasks() 
                                           if t.rjcode == rjcode_of_new_path and t.status == TaskStatus.PROCESSING]
                    if existing_tasks_for_rj:
                        task = existing_tasks_for_rj[0]
                        # 复用当前正在处理的同RJ号任务
                        original_source = task.source_path
                        task.source_path = str(conflict.new_path)
                        task.skip_archive = skip_archive_bool
                        # 确保任务状态为PROCESSED，以便继续执行
                        task.status = TaskStatus.PROCESSING
                        task.update_progress(10, "解压中")
                        logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                    else:
                        # 使用原有的冲突task_id逻辑
                        original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None
                        
                        if original_task:
                            # 更新原有任务的源路径，复用任务ID
                            original_source = original_task.source_path
                            original_task.source_path = str(conflict.new_path)
                            original_task.skip_archive = skip_archive_bool
                            original_task.status = TaskStatus.PROCESSING
                            original_task.update_progress(10, "解压中")
                            task = original_task
                            logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                        else:
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                else:
                    # 没有正在处理的同RJ任务时，使用原有的逻辑
                    original_task = engine.get_task(str(conflict.task_id)) if conflict.task_id else None

                    if original_task:
                        # 更新原有任务的源路径，复用任务ID
                        original_source = original_task.source_path
                        original_task.source_path = str(conflict.new_path)
                        original_task.skip_archive = skip_archive_bool
                        original_task.status = TaskStatus.PROCESSING
                        original_task.update_progress(10, "解压中")
                        task = original_task
                        logger.info(f"复用原有任务继续处理: {conflict.task_id}, 源路径: {original_source} -> {original_task.source_path}")
                    else:
                        # 检查是否有其他同RJ号的任务存在，如果有就复用
                        rjcode_of_new_path = engine._extract_rjcode(str(conflict.new_path))
                        if rjcode_of_new_path:
                            existing_rj_tasks = [t for t in engine.get_all_tasks() 
                                               if t.rjcode == rjcode_of_new_path]
                            if existing_rj_tasks:
                                task = existing_rj_tasks[0]
                                original_source = task.source_path
                                task.source_path = str(conflict.new_path)
                                task.skip_archive = skip_archive_bool
                                task.status = TaskStatus.PROCESSING
                                task.update_progress(10, "解压中")
                                logger.info(f"复用同RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {rjcode_of_new_path}")
                            else:
                                # 创建新任务
                                task = Task(
                                    task_type=TaskType.AUTO_PROCESS,
                                    source_path=str(conflict.new_path),
                                    auto_classify=True,
                                    skip_archive=skip_archive_bool
                                )
                                engine.tasks[task.id] = task
                                logger.info(f"创建新任务处理: {task.id}")
                        else:
                            # 创建新任务
                            task = Task(
                                task_type=TaskType.AUTO_PROCESS,
                                source_path=str(conflict.new_path),
                                auto_classify=True,
                                skip_archive=skip_archive_bool
                            )
                            engine.tasks[task.id] = task
                            logger.info(f"创建新任务处理: {task.id}")
                
                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()
                
                extracted_path = await extract_service.extract(task)
                if not extracted_path:
                    error_msg = task.error_message or "解压失败"
                    logger.error(f"处理冲突失败: {error_msg}")
                    return {"success": False, "error": error_msg}
                
                metadata = await metadata_service.fetch(extracted_path, task)
                task.task_metadata = metadata
                
                task.update_progress(60, "重命名文件夹")
                from app.core.rename_service import RenameService
                rename_service = RenameService()
                renamed_path = await rename_service.rename(extracted_path, task)
                
                task.update_progress(75, "过滤文件中")
                await filter_service.filter(renamed_path, task)
                
                if config.rename.flatten_single_subfolder:
                    renamed_path = rename_service._flatten_single_subfolder(renamed_path)
                    logger.info(f"保留新版 - 扁平化后路径: {renamed_path}")

                if config.rename.remove_empty_folders:
                    rename_service.remove_empty_folders(renamed_path, remove_root=False)

                # 简繁转换（与 AUTO_PROCESS 流程保持一致）
                if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                    from ..core.subtitle_sync_service import get_subtitle_sync_service
                    subtitle_svc = get_subtitle_sync_service()
                    task.update_progress(80, "字幕繁简转换中")
                    simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                    if simplify_result['converted_files'] > 0:
                        logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                   f"转换 {simplify_result['converted_files']} 个文件")

                task.update_progress(85, "移动到库存")
                final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                
                from app.core.task_engine import TaskEngine
                task_engine = TaskEngine()
                await task_engine._archive_source_file(task)
                
                task.status = TaskStatus.COMPLETED
                task.update_progress(100, f"问题作品已处理: {action_type}")
                task.completed_at = datetime.now()
                
                logger.info(f"保留新版完成：已解压并移动到 {final_path}，压缩包已归档")
                
                # 更新 ProcessedArchive 状态为 completed
                if is_in_processed:
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            else:
                # 如果是已解压的文件夹，直接移动
                if os.path.exists(conflict.new_path):
                    target_path = os.path.join(config.storage.library_path, os.path.basename(conflict.new_path))
                    await asyncio.to_thread(shutil.move, conflict.new_path, target_path)
                    logger.info(f"保留新版完成：已移动到 {target_path}")
            
            conflict.status = "KEEP_NEW"
            
        elif action_type == "KEEP_OLD":
            # 删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    os.remove(conflict.new_path)  # 删除压缩包
                else:
                    shutil.rmtree(conflict.new_path)  # 删除文件夹
            # 更新 ProcessedArchive 状态为 completed（用户选择保留旧版，新版任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (KEEP_OLD): {filename}")
            
            conflict.status = "KEEP_OLD"
            
        elif action_type == "MERGE":
            # 合并：保留两个版本，新版本加编号
            if is_archive:
                logger.info(f"合并：先解压压缩包 {conflict.new_path}")
                task = Task(
                    task_type=TaskType.AUTO_PROCESS,
                    source_path=conflict.new_path,
                    auto_classify=True
                )

                extract_service = ExtractService()
                filter_service = FilterService()
                metadata_service = MetadataService()
                classifier = SmartClassifier()

                extracted_path = await extract_service.extract(task)
                if extracted_path:
                    metadata = await metadata_service.fetch(extracted_path, task)

                    # 重命名
                    from app.core.rename_service import RenameService
                    rename_service = RenameService()
                    renamed_path = await rename_service.rename(extracted_path, task)

                    await filter_service.filter(renamed_path, task)

                    if config.rename.flatten_single_subfolder:
                        renamed_path = rename_service._flatten_single_subfolder(renamed_path)

                    if config.rename.remove_empty_folders:
                        rename_service.remove_empty_folders(renamed_path, remove_root=False)

                    # 简繁转换
                    if hasattr(config, 'asmr_sync') and getattr(config.asmr_sync, 'simplify_chinese_enabled', False):
                        from ..core.subtitle_sync_service import get_subtitle_sync_service
                        subtitle_svc = get_subtitle_sync_service()
                        simplify_result = subtitle_svc.convert_subtitles_to_simplified_in_folder(renamed_path)
                        if simplify_result['converted_files'] > 0:
                            logger.info(f"字幕繁简转换完成: 处理 {simplify_result['total_files']} 个文件, "
                                       f"转换 {simplify_result['converted_files']} 个文件")

                    # 修改metadata使文件夹名加编号
                    rjcode = metadata.get('rjcode', '')
                    target_base = os.path.join(config.storage.library_path, conflict.rjcode)
                    counter = 1
                    while os.path.exists(f"{target_base}({counter})"):
                        counter += 1
                    metadata['work_name'] = f"{metadata.get('work_name', '')}({counter})"

                    final_path = await classifier.classify_and_move(renamed_path, metadata, task)
                    os.remove(conflict.new_path)
                    logger.info(f"合并完成：新版本已保存为 {final_path}")
                    
                    # 更新 ProcessedArchive 状态为 completed
                    filename = os.path.basename(conflict.new_path)
                    archive_record = db.query(ProcessedArchive).filter(
                        ProcessedArchive.filename == filename
                    ).first()
                    if archive_record:
                        archive_record.status = 'completed'
                        archive_record.processed_at = datetime.now()
                        db.commit()
                        logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed: {filename}")
            
            conflict.status = "MERGE"
            
        elif action_type == "SKIP":
            # 跳过，删除新版本
            if os.path.exists(conflict.new_path):
                if os.path.isfile(conflict.new_path):
                    os.remove(conflict.new_path)
                else:
                    shutil.rmtree(conflict.new_path)
            # 更新 ProcessedArchive 状态为 completed（用户选择跳过，任务结束）
            if is_archive:
                filename = os.path.basename(conflict.new_path)
                archive_record = db.query(ProcessedArchive).filter(
                    ProcessedArchive.filename == filename
                ).first()
                if archive_record:
                    archive_record.status = 'completed'
                    archive_record.processed_at = datetime.now()
                    db.commit()
                    logger.info(f"冲突解决后更新 ProcessedArchive 状态为 completed (SKIP): {filename}")
            
            conflict.status = "SKIP"
        
        # 更新关联任务的状态
        if conflict.task_id:
            engine = get_task_engine()
            from ..core.task_engine import TaskStatus
            engine.update_task_status(
                conflict.task_id, 
                TaskStatus.COMPLETED,
                f"问题作品已处理: {action_type}"
            )
        
        db.commit()
        return {"message": "处理成功"}
        
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as e:
        db.rollback()
        logger.error(f"处理冲突失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

async def scan_processed_archives():
    """启动时扫描已处理压缩包目录，同步数据库"""
    import os
    import re
    from datetime import datetime
    from ..models.database import ProcessedArchive, get_db
    from ..config.settings import get_config
    import uuid
    
    config = get_config()
    processed_dir = config.storage.processed_archives_path
    
    if not os.path.exists(processed_dir):
        logger.info(f"已处理压缩包目录不存在: {processed_dir}")
        return
    
    logger.info(f"开始扫描已处理压缩包目录: {processed_dir}")
    
    db = next(get_db())
    try:
        # 清理重复记录（保留最新的）
        all_archives = db.query(ProcessedArchive).order_by(ProcessedArchive.processed_at.desc()).all()
        seen_filenames = {}
        duplicates = []
        for archive in all_archives:
            if archive.filename in seen_filenames:
                duplicates.append(archive)
            else:
                seen_filenames[archive.filename] = archive
        
        if duplicates:
            logger.info(f"发现 {len(duplicates)} 个重复记录，正在清理...")
            for dup in duplicates:
                db.delete(dup)
            db.commit()
            logger.info("重复记录清理完成")
        
        # 重新获取清理后的记录
        db_archives = {a.filename: a for a in db.query(ProcessedArchive).all()}
        
        # 扫描目录中的文件
        found_files = []
        for filename in await asyncio.to_thread(os.listdir, processed_dir):
            file_path = os.path.join(processed_dir, filename)
            if os.path.isfile(file_path):
                found_files.append(filename)
                file_size = os.path.getsize(file_path)
                
                # 提取RJ号
                rjcode = None
                match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', filename, re.IGNORECASE)
                if match:
                    rjcode = match.group(0).upper()
                
                if filename in db_archives:
                    # 更新现有记录（只更新路径和大小，不更新时间）
                    archive = db_archives[filename]
                    archive.current_path = file_path
                    archive.file_size = file_size
                    # 注意：不要在这里更新 processed_at，扫描只是同步文件状态，不是重新处理
                    logger.info(f"更新已处理压缩包记录路径: {filename}")
                else:
                    # 创建新记录
                    new_archive = ProcessedArchive(
                        id=str(uuid.uuid4()),
                        original_path=file_path,
                        current_path=file_path,
                        filename=filename,
                        rjcode=rjcode or '',
                        file_size=file_size,
                        processed_at=datetime.now(),
                        process_count=1,
                        task_id='',
                        status='completed'
                    )
                    db.add(new_archive)
                    logger.info(f"添加新的已处理压缩包记录: {filename}")
        
        # 清理数据库中不存在的记录
        for filename, archive in list(db_archives.items()):
            if filename not in found_files:
                archive_path = os.path.join(processed_dir, filename)
                if not os.path.exists(archive_path):
                    logger.info(f"删除不存在的压缩包记录: {filename}")
                    db.delete(archive)
        
        db.commit()
        logger.info(f"已处理压缩包目录扫描完成，共发现 {len(found_files)} 个文件")
        
    except Exception as e:
        logger.error(f"扫描已处理压缩包目录失败: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

# 已处理压缩包API
@app.post("/api/processed-archives/scan")
async def scan_processed_archives_api():
    """手动触发扫描已处理压缩包目录"""
    try:
        await scan_processed_archives()
        return {"message": "扫描完成"}
    except Exception as e:
        logger.error(f"手动扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")

@app.get("/api/processed-archives")
async def get_processed_archives(
    search: Optional[str] = None,
    sort_by: Optional[str] = "processed_at",
    sort_order: Optional[str] = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """获取已处理压缩包列表，支持搜索和排序
    
    Args:
        search: 搜索关键词（匹配RJ号、文件名）
        sort_by: 排序字段（rjcode, file_size, process_count, status, processed_at）
        sort_order: 排序方向（asc, desc）
    """
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        query = db.query(ProcessedArchive)
        
        # 搜索功能
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (ProcessedArchive.rjcode.contains(search)) |
                (ProcessedArchive.filename.contains(search))
            )
        
        # 排序功能
        valid_sort_fields = {
            "rjcode": ProcessedArchive.rjcode,
            "file_size": ProcessedArchive.file_size,
            "process_count": ProcessedArchive.process_count,
            "status": ProcessedArchive.status,
            "processed_at": ProcessedArchive.processed_at
        }
        
        sort_field = valid_sort_fields.get(sort_by, ProcessedArchive.processed_at)
        
        if sort_order.lower() == "desc":
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
        
        total = query.count()
        safe_limit = max(1, min(int(limit or 50), 500))
        safe_offset = max(0, int(offset or 0))
        archives = query.offset(safe_offset).limit(safe_limit).all()
        return {
            "archives": [archive.to_dict() for archive in archives],
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
        }
    finally:
        db.close()

@app.post("/api/processed-archives/{archive_id}/reprocess")
async def reprocess_archive(archive_id: str):
    """重新处理已归档的压缩包"""
    from ..models.database import ProcessedArchive, get_db
    
    db = next(get_db())
    try:
        archive = db.query(ProcessedArchive).filter(ProcessedArchive.id == archive_id).first()
        if not archive:
            raise HTTPException(status_code=404, detail="压缩包记录不存在")
        
        # 检查文件是否还存在
        if not os.path.exists(archive.current_path):
            raise HTTPException(status_code=404, detail="压缩包文件不存在，可能已被删除")
        
        # 直接从 processed 目录解压，避免复制到 SSD
        logger.info(f"直接从 processed 目录重新解压: {archive.current_path}")
        
        # 检查是否已有处理同RJ号的现存任务
        engine = get_task_engine()
        existing_tasks_for_rj = [t for t in engine.get_all_tasks()
                               if t.rjcode == archive.rjcode]

        if existing_tasks_for_rj:
            # 复用已有任务
            task = existing_tasks_for_rj[0]
            original_source = task.source_path
            old_status = task.status
            task.source_path = archive.current_path
            task.skip_archive = True  # 标记跳过归档（因为文件已在 processed 目录）
            task.status = TaskStatus.PENDING
            task.update_progress(0, "待处理")
            # 将任务加入队列以供 worker 执行
            await engine.queue.put(task)
            logger.info(f"复用现有RJ号任务: {task.id}, 源路径: {original_source} -> {task.source_path}, RJ: {archive.rjcode}, 状态: {old_status} -> {task.status}")
        else:
            # 创建新任务（标记为重新处理，直接从 processed 目录解压）
            task = Task(
                task_type=TaskType.AUTO_PROCESS,
                source_path=archive.current_path,  # 直接使用 processed 目录中的文件
                auto_classify=get_config().watcher.auto_classify,
                skip_archive=True  # 标记跳过归档（因为文件已在 processed 目录）
            )
            await engine.submit(task)
            # 注意：submit 会自动添加 task 到 engine.tasks 和队列中
        
        # 更新记录状态和重新处理时间
        archive.status = 'reprocessing'
        archive.processed_at = datetime.now()
        archive.process_count = (archive.process_count or 0) + 1
        db.commit()
        
        return {
            "message": "已创建重新处理任务",
            "task_id": task.id,
            "filename": archive.filename,
            "rjcode": archive.rjcode
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新处理压缩包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新处理失败: {str(e)}")
    finally:
        db.close()

# 库存管理API
@app.get("/api/library/libraries")
async def get_library_definitions():
    manager = get_library_manager()
    current_library = manager.get_library_definition()
    return {
        "libraries": manager.list_libraries(),
        "default_library_id": current_library.id,
        "default_extract_library_id": manager.default_extract_library_id(),
    }


@app.post("/api/library/test-connection")
async def test_library_connection(request: Request):
    try:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="请求体必须为有效 JSON")
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="请求体必须为 JSON 对象")
        library = data.get("library") or data
        manager = get_library_manager()
        return await manager.test_connection(library)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存连接测试失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存连接测试失败: {str(e)}")


@app.get("/api/library/storage-info")
async def get_library_storage_info(library_id: str):
    try:
        manager = get_library_manager()
        library = manager.get_library_definition(library_id)
        if library.type != "synology_filestation" or not library.synology:
            raise HTTPException(status_code=400, detail="目标库存不是群晖库存")
        client = manager.get_cached_synology_client(library.synology)
        storage_info = await client.get_storage_info()
        return {
            "library_id": library.id,
            "library_name": library.name,
            **storage_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"获取库存空间失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"获取库存空间失败: {str(e)}")


@app.get("/api/library/browser/files")
async def browse_library_files(
    library_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
    search: str = "",
    current_path: Optional[str] = None,
    sort_by: str = "size",
    sort_order: str = "desc",
    force_refresh: bool = False,
    search_exact: bool = False,
    search_result_kind: str = "all",
):
    try:
        manager = get_library_manager()
        current_library = manager.get_library_definition(library_id)
        keyword = str(search or "").strip()
        use_remote_global_search = (
            bool(keyword)
            and current_library.type == "synology_filestation"
        )
        if use_remote_global_search:
            data = await manager.global_search_files(
                current_library.id,
                keyword,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
            )
            browse_root_path = current_library.browse_root_path or current_library.root_path
            display_current_path = current_path or browse_root_path
            data["browse_root_path"] = browse_root_path
            data["current_path"] = display_current_path
            normalized_browse_root = str(PurePosixPath(browse_root_path or "/"))
            normalized_current_path = str(PurePosixPath(display_current_path or normalized_browse_root))
            if normalized_current_path in {"", "."}:
                normalized_current_path = normalized_browse_root or "/"
            if normalized_current_path == normalized_browse_root:
                data["parent_path"] = None
            else:
                data["parent_path"] = str(PurePosixPath(normalized_current_path).parent)
        else:
            data = await manager.list_files(
                library_id,
                page=page,
                page_size=page_size,
                search=search,
                current_path=current_path,
                sort_by=sort_by,
                sort_order=sort_order,
                force_refresh=force_refresh,
                search_exact=search_exact,
                search_result_kind=search_result_kind,
            )
        data["libraries"] = manager.list_libraries()
        data["library_id"] = data.get("library_id") or current_library.id
        return data
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存浏览失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存浏览失败: {str(e)}")


@app.get("/api/library/browser/stats")
async def get_library_browser_stats(force_refresh: bool = False, library_id: Optional[str] = None):
    try:
        manager = get_library_manager()
        return await manager.ensure_stats(force=force_refresh, library_id=library_id)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存统计失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存统计失败: {str(e)}")


@app.post("/api/library/browser/stats/cancel")
async def cancel_library_browser_stats(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        if not library_id:
            raise HTTPException(status_code=400, detail="缺少库存 ID")
        manager = get_library_manager()
        return await manager.cancel_stats(library_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消库存统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消库存统计失败: {str(e)}")


@app.post("/api/library/browser/compute-folder-size")
async def compute_folder_size(request: Request):
    """手动计算并缓存指定文件夹的大小（供社团目录右键菜单触发）。"""
    try:
        data = await request.json()
        folder_path = str(data.get("path") or "").strip()
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")

        manager = get_library_manager()

        def _compute():
            return manager._cached_path_size(folder_path)

        size = await asyncio.to_thread(_compute)
        return {"path": folder_path, "size": size}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"计算文件夹大小失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"计算文件夹大小失败: {str(e)}")


@app.get("/api/library/browser/stats/logs")
async def get_library_browser_stats_logs(library_id: Optional[str] = None, lines: int = 200):
    try:
        manager = get_library_manager()
        return manager.read_stats_logs(library_id=library_id, lines=lines)
    except Exception as e:
        logger.error(f"鑾峰彇搴撳瓨缁熻鏃ュ織澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"鑾峰彇搴撳瓨缁熻鏃ュ織澶辫触: {str(e)}")


@app.post("/api/library/browser/folder-contents")
async def get_library_browser_folder_contents(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        manager = get_library_manager()
        return await manager.folder_contents(library_id, folder_path)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"获取库存文件夹内容失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"获取库存文件夹内容失败: {str(e)}")


class LibraryListSubdirectoriesRequest(BaseModel):
    """列出库存路径下一级子目录请求"""
    library_id: str
    path: Optional[str] = ""


@app.post("/api/library/list-subdirectories")
async def list_library_subdirectories(request: LibraryListSubdirectoriesRequest):
    """列出指定库存路径下一级子目录（不递归）。"""
    if not str(request.library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少 library_id")
    try:
        manager = get_library_manager()
        return await manager.list_first_level_directories(request.library_id, request.path)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"列子目录失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"列子目录失败: {str(e)}")


@app.post("/api/library/browser/mojibake-preview")
async def get_library_browser_mojibake_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        selected_paths = data.get("selected_paths") or []
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")
        manager = get_library_manager()
        return await manager.preview_mojibake_repairs(library_id, folder_path, selected_paths=selected_paths)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log_synology_err(f"获取乱码修复预览失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取乱码修复预览失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview")
async def get_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        request_id = data.get("request_id")
        rules = data.get("rules")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        try:
            return await manager.filter_delete_preview(library_id, folder_path, rules=rules, request_id=request_id)
        finally:
            manager._finish_filter_preview_request(request_id)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"过滤删除预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"过滤删除预览失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/start")
async def start_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        folder_path = data.get("path")
        rules = data.get("rules")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少目标目录路径")
        manager = get_library_manager()
        return await manager.start_filter_delete_preview_job(library_id, folder_path, rules=rules)
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"启动过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动过滤删除预审失败: {str(e)}")


@app.get("/api/library/browser/filter-delete-preview/status")
async def get_library_browser_filter_delete_preview_status(job_id: str):
    try:
        manager = get_library_manager()
        return manager.get_filter_delete_preview_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except Exception as e:
        _log_synology_err(f"获取过滤删除预审状态失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取过滤删除预审状态失败: {str(e)}")


@app.post("/api/library/browser/filter-delete-preview/cancel")
async def cancel_library_browser_filter_delete_preview(request: Request):
    try:
        data = await request.json()
        request_id = data.get("request_id")
        job_id = data.get("job_id")
        manager = get_library_manager()
        if job_id:
            return await manager.cancel_filter_delete_preview_job(job_id)
        return manager.cancel_filter_delete_preview(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="过滤删除预审任务不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消过滤删除预审失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消过滤删除预审失败: {str(e)}")


@app.post("/api/library/browser/rename")
async def rename_library_browser_item(request: Request):
    path = ""
    new_name = ""
    library_id = None
    skip_activity_log = False
    batch_id = ""
    rename_context = ""
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        new_name = str(data.get("new_name") or "").strip()
        library_id = data.get("library_id")
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        rename_context = str(data.get("rename_context") or "").strip()
        if not path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        manager = get_library_manager()
        result = await manager.rename(library_id, path, new_name)
        try:
            from ..core.activity_log_service import log_api_rename_action
            if not skip_activity_log:
                new_path = str(result.get("new_path") or result.get("path") or "").strip() if isinstance(result, dict) else ""
                log_api_rename_action(
                    action="rename",
                    success=True,
                    source_path=path,
                    new_path=new_path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名失败记录失败", exc_info=True)
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存重命名失败: {e}", e)
        try:
            from ..core.activity_log_service import log_api_rename_action
            if path and not skip_activity_log:
                log_api_rename_action(
                    action="rename",
                    success=False,
                    source_path=path,
                    old_name=os.path.basename(path),
                    new_name=new_name,
                    batch_id=batch_id or None,
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
        except Exception:
            logger.debug("[操作记录] 库存重命名异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存重命名失败: {str(e)}")


@app.post("/api/library/browser/batch-rename")
async def batch_rename_library_browser_items(request: Request):
    try:
        data = await request.json()
        library_id = data.get("library_id")
        items = data.get("items") or []
        rename_context = str(data.get("rename_context") or "").strip()
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="缺少批量重命名项")

        from ..core.activity_log_service import log_api_rename_action, log_batch_manual_rename_result
        import uuid

        manager = get_library_manager()
        batch_id = f"mojibake-{uuid.uuid4().hex}"
        path_replacements: list[dict[str, str]] = []
        results = []
        success_count = 0
        failed_count = 0

        def remap_path(raw_path: str) -> str:
            current = str(raw_path or "").replace("\\", "/").rstrip("/")
            for replacement in path_replacements:
                old_path = str(replacement.get("old_path") or "").replace("\\", "/").rstrip("/")
                new_path = str(replacement.get("new_path") or "").replace("\\", "/").rstrip("/")
                if not old_path or not new_path:
                    continue
                if current == old_path:
                    current = new_path
                    continue
                if current.startswith(f"{old_path}/"):
                    current = f"{new_path}{current[len(old_path):]}"
            return current

        for item in items:
            source_path = str((item or {}).get("path") or "").strip()
            new_name = str((item or {}).get("new_name") or "").strip()
            current_name = str((item or {}).get("current_name") or os.path.basename(source_path) or "").strip()
            mapped_path = remap_path(source_path)
            if not mapped_path or not new_name or new_name == current_name:
                failed_count += 1
                results.append({
                    "path": source_path,
                    "old_name": current_name,
                    "new_name": new_name,
                    "success": False,
                    "error": "目标名称无效或无变化",
                })
                continue
            try:
                rename_result = await manager.rename(library_id, mapped_path, new_name)
                new_path = str(rename_result.get("new_path") or "").strip()
                if new_path and new_path != mapped_path:
                    path_replacements.append({"old_path": mapped_path, "new_path": new_path})
                log_api_rename_action(
                    action="batch_rename_item",
                    success=True,
                    source_path=mapped_path,
                    new_path=new_path,
                    old_name=current_name,
                    new_name=new_name,
                    batch_id=batch_id,
                    library_id=str(library_id or "") or None,
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
                success_count += 1
                results.append({
                    "path": mapped_path,
                    "old_name": current_name,
                    "new_name": new_name,
                    "new_path": new_path,
                    "success": True,
                })
            except Exception as exc:
                failed_count += 1
                error_text = str(getattr(exc, "detail", "") or exc)
                log_api_rename_action(
                    action="batch_rename_item",
                    success=False,
                    source_path=mapped_path,
                    old_name=current_name,
                    new_name=new_name,
                    batch_id=batch_id,
                    library_id=str(library_id or "") or None,
                    error=error_text,
                    status="failed",
                    extra_detail={"rename_context": rename_context} if rename_context else None,
                )
                results.append({
                    "path": mapped_path,
                    "old_name": current_name,
                    "new_name": new_name,
                    "success": False,
                    "error": error_text,
                })

        log_batch_manual_rename_result(
            batch_id=batch_id,
            total_count=len(items),
            success_count=success_count,
            failed_count=failed_count,
            results=results,
            source_path=str(data.get("path") or "").strip(),
            rename_context=rename_context,
        )
        return {
            "batch_id": batch_id,
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_items": [item for item in results if not item.get("success")],
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存批量重命名失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量重命名失败: {str(e)}")


@app.post("/api/library/browser/delete")
async def delete_library_browser_item(request: Request):
    path = ""
    library_id = None
    skip_activity_log = False
    batch_id = ""
    try:
        data = await request.json()
        path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        skip_activity_log = bool(data.get("skip_activity_log"))
        batch_id = str(data.get("batch_id") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="缺少路径")
        manager = get_library_manager()
        result = await manager.delete(library_id, path, confirmed=confirmed)
        try:
            from ..core.activity_log_service import log_api_delete_action
            if confirmed and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=True,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="dir" if str(result.get("type") or "").strip() == "folder" else "file",
                    library_id=str(library_id or "") or None,
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除记录失败", exc_info=True)
        return result
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(exc.detail or exc),
                    status="failed",
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除失败记录失败", exc_info=True)
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存删除失败: {e}", e)
        try:
            from ..core.activity_log_service import log_api_delete_action
            if path and not skip_activity_log:
                log_api_delete_action(
                    action="delete",
                    success=False,
                    source_path=path,
                    item_name=os.path.basename(path),
                    item_type="unknown",
                    library_id=str(library_id or "") or None,
                    error=str(e),
                    batch_id=batch_id or None,
                )
        except Exception:
            logger.debug("[操作记录] 库存删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存删除失败: {str(e)}")


@app.post("/api/library/browser/batch-delete")
async def batch_delete_library_browser_items(request: Request):
    paths: list[str] = []
    library_id = None
    batch_id = ""
    try:
        data = await request.json()
        paths = [str(p or "").strip() for p in (data.get("paths") or []) if str(p or "").strip()]
        library_id = data.get("library_id")
        confirmed = data.get("confirmed", False)
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        manager = get_library_manager()
        result = await manager.batch_delete(library_id, paths, confirmed=confirmed)
        try:
            from ..core.activity_log_service import log_api_delete_action, log_batch_api_delete_result
            if confirmed and isinstance(result, dict):
                batch_id = str(data.get("batch_id") or "").strip() or str(uuid.uuid4())
                success_count = int(result.get("success_count") or 0)
                failed_paths = result.get("failed_paths") or []
                failed_count = len(failed_paths) if isinstance(failed_paths, list) else 0
                per_item_results = []

                failed_map = {}
                if isinstance(failed_paths, list):
                    for item in failed_paths:
                        p = str((item or {}).get("path") or "").strip()
                        if p:
                            failed_map[p] = str((item or {}).get("error") or "").strip()

                for p in paths:
                    err = failed_map.get(p, "")
                    ok = not bool(err)
                    log_api_delete_action(
                        action="batch_delete_item",
                        success=ok,
                        source_path=p,
                        item_name=os.path.basename(p),
                        item_type="unknown",
                        library_id=str(library_id or "") or None,
                        error=err,
                        batch_id=batch_id,
                    )
                    per_item_results.append({
                        "path": p,
                        "success": ok,
                        "error": err,
                    })

                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=success_count,
                    failed_count=failed_count,
                    results=per_item_results,
                    source_path=paths[0] if paths else "",
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除记录失败", exc_info=True)
        return result
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存批量删除失败: {e}", e)
        try:
            from ..core.activity_log_service import log_batch_api_delete_result
            if paths:
                log_batch_api_delete_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=0,
                    failed_count=len(paths),
                    results=[{"path": p, "success": False, "error": str(e)} for p in paths],
                    source_path=paths[0],
                )
        except Exception:
            logger.debug("[操作记录] 库存批量删除异常记录失败", exc_info=True)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量删除失败: {str(e)}")


class LibraryBrowserListFoldersRequest(BaseModel):
    """轻量目录浏览请求（仅本地库，仅返回子目录，不计算 size）。"""
    library_id: str
    path: Optional[str] = ""


@app.post("/api/library/browser/list-folders")
async def list_library_browser_folders(request: LibraryBrowserListFoldersRequest):
    """供"移动到..."对话框使用：只列出指定路径下的一级子目录，不算 size、不递归。"""
    if not str(request.library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少 library_id")
    try:
        manager = get_library_manager()
        return await manager.list_local_folders_only(request.library_id, request.path or None)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log_synology_err(f"列出本地子目录失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"列出本地子目录失败: {str(e)}")


class LibraryBrowserMoveRequest(BaseModel):
    """本地库批量移动请求（源/目标都必须是本地库）。"""
    source_library_id: str
    target_library_id: str
    paths: list[str]
    target_path: Optional[str] = ""
    conflict_strategy: Optional[str] = "suffix"  # suffix / overwrite / skip
    overwrite: bool = False  # 兼容旧字段


@app.post("/api/library/browser/move")
async def move_library_browser_items(request: LibraryBrowserMoveRequest):
    if not request.paths:
        raise HTTPException(status_code=400, detail="待移动项不能为空")
    if not str(request.source_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少源库存")
    if not str(request.target_library_id or "").strip():
        raise HTTPException(status_code=400, detail="缺少目标库存")
    try:
        manager = get_library_manager()
        return await manager.move_local_items(
            source_library_id=request.source_library_id,
            target_library_id=request.target_library_id,
            paths=list(request.paths or []),
            target_path=request.target_path or None,
            conflict_strategy=str(request.conflict_strategy or "suffix"),
            overwrite=bool(request.overwrite),
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log_synology_err(f"库存批量移动失败: {e}", e)
        raise HTTPException(status_code=_synology_http_status(e), detail=f"库存批量移动失败: {str(e)}")


@app.post("/api/library/browser/open-folder")
async def open_library_browser_folder(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        library_id = data.get("library_id")
        force_local = data.get("force_local", False)
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        manager = get_library_manager()
        return await manager.open_folder(library_id, path, force_local=force_local)
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"库存打开目录失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"库存打开目录失败: {str(e)}")


@app.get("/api/library/files")
async def get_library_files():
    """获取库内所有文件（只扫描前两级目录）"""
    try:
        config = get_config()
        library_path = config.storage.library_path
        
        if not os.path.exists(library_path):
            return {"files": []}
        
        # 查询 ProcessedArchive 数据库获取解压时间
        from ..models.database import ProcessedArchive, get_db
        db = next(get_db())
        
        # 构建文件名到解压时间的映射
        archive_times = {}
        for archive in db.query(ProcessedArchive).all():
            archive_name = os.path.basename(archive.current_path)
            archive_times[archive_name] = archive.processed_at
        
        items = []
        item_id = 0
        
        # 只遍历前两级目录
        for item in os.listdir(library_path):
            item_path = os.path.join(library_path, item)
            
            # 跳过冲突文件夹和隐藏文件
            if item.startswith('_') or item.startswith('.'):
                continue
            
            # 如果是文件夹（如 RJ012xxxxx），遍历其子目录
            if os.path.isdir(item_path):
                for subitem in os.listdir(item_path):
                    subitem_path = os.path.join(item_path, subitem)
                    
                    # 跳过隐藏文件
                    if subitem.startswith('.'):
                        continue
                    
                    try:
                        stat = os.stat(subitem_path)
                        # 提取RJ号
                        rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', subitem, re.IGNORECASE)
                        rjcode = rj_match.group(0).upper() if rj_match else None
                        
                        # 计算文件夹大小或获取文件大小
                        size = 0
                        if os.path.isdir(subitem_path):
                            for dirpath, dirnames, filenames in os.walk(subitem_path):
                                for f in filenames:
                                    fp = os.path.join(dirpath, f)
                                    try:
                                        size += os.path.getsize(fp)
                                    except:
                                        pass
                        else:
                            size = stat.st_size
                        
                        # 获取解压时间（优先使用 processed_at，否则使用文件系统时间）
                        unzip_time = None
                        if subitem in archive_times:
                            unzip_time = archive_times[subitem].isoformat()
                        else:
                            unzip_time = datetime.fromtimestamp(stat.st_mtime).isoformat()
                        
                        items.append({
                            "id": str(item_id),
                            "name": subitem,
                            "path": subitem_path,
                            "rjcode": rjcode,
                            "size": size,
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "unzip_time": unzip_time,
                            "is_directory": os.path.isdir(subitem_path)
                        })
                        item_id += 1
                    except Exception as e:
                        logger.warning(f"获取项目信息失败: {subitem_path}, {e}")
            else:
                # 根目录下的文件
                try:
                    stat = os.stat(item_path)
                    rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                    rjcode = rj_match.group(0).upper() if rj_match else None
                    
                    # 获取解压时间
                    unzip_time = None
                    if item in archive_times:
                        unzip_time = archive_times[item].isoformat()
                    else:
                        unzip_time = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    
                    items.append({
                        "id": str(item_id),
                        "name": item,
                        "path": item_path,
                        "rjcode": rjcode,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "unzip_time": unzip_time,
                        "is_directory": False
                    })
                    item_id += 1
                except Exception as e:
                    logger.warning(f"获取项目信息失败: {item_path}, {e}")
        
        # 按解压时间排序（最新的在前）
        items.sort(key=lambda x: x["unzip_time"] or x["modified_time"], reverse=True)
        
        return {"files": items}
        
    except Exception as e:
        _log_synology_err(f"获取库文件失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取库文件失败: {str(e)}")

@app.post("/api/library/folder-contents")
@app.post("/api/library/folder-content")
async def get_library_folder_contents(request: Request):
    """获取指定本地文件夹的所有子文件（递归）"""
    try:
        data = await request.json()
        folder_path = data.get("path")
        if not folder_path:
            raise HTTPException(status_code=400, detail="缺少文件夹路径")

        target_path = os.path.abspath(folder_path)

        if not os.path.exists(target_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        if not os.path.isdir(target_path):
            raise HTTPException(status_code=400, detail="目标不是文件夹")

        items = []
        item_id = 0
        for root, _, files in os.walk(target_path):
            for filename in files:
                if filename.startswith('.'):
                    continue
                file_path = os.path.join(root, filename)
                try:
                    stat = os.stat(file_path)
                    relative_path = os.path.relpath(file_path, target_path).replace("\\", "/")
                    items.append({
                        "id": str(item_id),
                        "name": filename,
                        "path": file_path,
                        "relative_path": relative_path,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                    item_id += 1
                except Exception as e:
                    logger.warning(f"读取子文件失败: {file_path}, {e}")

        items.sort(key=lambda x: x["relative_path"])
        return {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "total_files": len(items),
            "items": items
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_synology_err(f"获取文件夹内容失败: {e}", e)
        raise HTTPException(status_code=500, detail=f"获取文件夹内容失败: {str(e)}")

@app.post("/api/library/rename")
async def rename_library_file(request: Request):
    """重命名库内文件或文件夹"""
    try:
        data = await request.json()
        old_path = data.get("path")
        new_name = data.get("new_name")
        
        if not old_path or not new_name:
            raise HTTPException(status_code=400, detail="缺少必要参数")
        
        if not os.path.exists(old_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 构建新路径
        parent_dir = os.path.dirname(old_path)
        new_path = os.path.join(parent_dir, new_name)
        
        # 检查新名称是否已存在
        if os.path.exists(new_path):
            raise HTTPException(status_code=400, detail="新名称已存在")
        
        # 执行重命名
        os.rename(old_path, new_path)
        logger.info(f"重命名成功: {old_path} -> {new_path}")
        
        return {"message": "重命名成功", "new_path": new_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重命名失败: {str(e)}")

@app.post("/api/library/api-rename")
async def api_rename_library_file(request: Request):
    """使用API重新获取元数据并重命名"""
    file_path = ""
    library_id = None
    rjcode = ""
    old_name = ""
    new_name = ""
    try:
        data = await request.json()
        file_path = str(data.get("path") or "").strip()
        library_id = data.get("library_id")
        manager = get_library_manager() if library_id else None
        library = manager.get_library_definition(library_id) if library_id else None
        is_remote_library = bool(library and library.type == "synology_filestation")
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")
        
        if not is_remote_library and not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 提取RJ号
        import re
        target_name = str(PurePosixPath(file_path).name) if is_remote_library else os.path.basename(file_path)
        rj_match = re.search(r'[RVB]J\d{6,8}', target_name, re.IGNORECASE)
        if not rj_match:
            raise HTTPException(status_code=400, detail="无法从文件名提取RJ号")
        
        rjcode = rj_match.group(0).upper()
        old_name = target_name
        logger.info(f"API重新命名: {file_path}, RJ号: {rjcode}")
        
        # 获取元数据（强制刷新，不使用缓存）
        from ..core.metadata_service import MetadataService
        from ..models.database import WorkMetadata as WorkMetadataModel, get_db
        metadata_service = MetadataService()
        
        try:
            # 清除该RJ号的缓存（强制重新获取）
            db = next(get_db())
            try:
                deleted_count = db.query(WorkMetadataModel).filter(
                    WorkMetadataModel.rjcode == rjcode
                ).delete()
                db.commit()
                if deleted_count > 0:
                    logger.info(f"[{rjcode}] 已清除缓存，准备重新获取元数据")
                else:
                    logger.info(f"[{rjcode}] 无缓存，将直接获取元数据")
            except Exception as e:
                logger.warning(f"[{rjcode}] 清除缓存失败: {e}")
                db.rollback()
            finally:
                db.close()
            
            # 创建临时任务对象（用于进度更新，虽然这里不需要）
            from ..core.task_engine import Task, TaskType
            temp_task = Task(
                task_type=TaskType.METADATA,
                source_path=file_path
            )
            
            metadata = await metadata_service.fetch(file_path, temp_task)
            logger.info(f"获取到元数据: {metadata}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取元数据失败: {e}")
            raise HTTPException(status_code=_synology_http_status(e), detail=f"获取元数据失败: {str(e)}")
        
        # 生成新名称
        work_name = metadata.get('work_name', '')
        if not work_name:
            raise HTTPException(status_code=422, detail="获取到的作品名称为空，请检查 DLsite 元数据是否可用")
        
        config = get_config()
        logger.info(f"[API RENAME] 读取到的模板: '{config.rename.template}' (长度: {len(config.rename.template)})")
        logger.info(f"[API RENAME] api_rename_follow_template: {config.rename.api_rename_follow_template}")
        logger.info(f"[API RENAME] use_japanese_metadata: {config.rename.use_japanese_metadata}")

        # 根据配置决定是否遵循重命名模板
        if config.rename.api_rename_follow_template:
            # 使用重命名服务生成名称
            from ..core.rename_service import RenameService
            rename_service = RenameService()

            # 创建临时任务对象用于重命名
            from ..core.task_engine import Task, TaskType
            temp_task = Task(
                task_type=TaskType.RENAME,
                source_path=file_path
            )
            temp_task.task_metadata = metadata

            # 如果启用了日语元数据，获取日语版本
            japanese_metadata = None
            if config.rename.use_japanese_metadata:
                logger.info(f"[{rjcode}] 启用日语元数据，正在获取...")
                japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
                if japanese_metadata:
                    logger.info(f"[{rjcode}] 日语元数据获取成功: maker_name={japanese_metadata.get('maker_name')}")
                else:
                    logger.warning(f"[{rjcode}] 日语元数据获取失败，将使用当前语言元数据")

            # 编译名称
            new_name = rename_service._compile_name(metadata, japanese_metadata)
            new_name = rename_service._sanitize_filename(new_name)
            logger.info(f"[{rjcode}] 使用重命名模板生成名称: {new_name}")
        else:
            # 简单格式：RJ号 + 作品名
            import re
            def sanitize_filename(name):
                # 移除或替换Windows不允许的字符
                name = re.sub(r'[<>:"/\\|?*]', '_', name)
                # 移除控制字符
                name = re.sub(r'[\x00-\x1f\x7f]', '', name)
                # 移除末尾的空格和点
                name = name.rstrip(' .')
                return name
            
            new_name = f"{rjcode} {sanitize_filename(work_name)}"
            logger.info(f"[{rjcode}] 使用简单格式生成名称: {new_name}")
        
        # 构建新路径
        if is_remote_library:
            parent_dir = str(PurePosixPath(file_path).parent)
            new_path = str(PurePosixPath(parent_dir) / new_name)
        else:
            parent_dir = os.path.dirname(file_path)
            new_path = os.path.join(parent_dir, new_name)
        
        # 检查新名称是否已存在
        if not is_remote_library and os.path.exists(new_path) and new_path != file_path:
            raise HTTPException(status_code=400, detail="新名称已存在")
        
        if new_path == file_path:
            try:
                from ..core.activity_log_service import log_api_rename_action

                log_api_rename_action(
                    action="api_rename",
                    success=True,
                    source_path=file_path,
                    new_path=new_path,
                    old_name=old_name,
                    new_name=new_name,
                    rjcode=rjcode or None,
                    library_id=str(library_id or "") or None,
                    extra_detail={"no_change": True},
                )
            except Exception:
                logger.debug("[操作记录] API 重命名无变化记录失败", exc_info=True)
            return {"message": "名称已是最新，无需重命名", "name": new_name}

        # 执行重命名
        if is_remote_library:
            await manager.rename(library_id, file_path, new_name)
        else:
            os.rename(file_path, new_path)
        logger.info(f"API重命名成功: {file_path} -> {new_path}")
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=True,
                source_path=file_path,
                new_path=new_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
            )
        except Exception:
            logger.debug("[操作记录] API 重命名成功记录失败", exc_info=True)

        return {
            "message": "API重命名成功",
            "old_name": os.path.basename(file_path),
            "new_name": new_name,
            "path": new_path,
            "metadata": metadata
        }
        
    except HTTPException as exc:
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
                error=str(exc.detail or exc),
                status="failed",
            )
        except Exception:
            logger.debug("[操作记录] API 重命名 HTTP 异常记录失败", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"API重命名失败: {e}", exc_info=True)
        try:
            from ..core.activity_log_service import log_api_rename_action

            log_api_rename_action(
                action="api_rename",
                success=False,
                source_path=file_path,
                old_name=old_name,
                new_name=new_name,
                rjcode=rjcode or None,
                library_id=str(library_id or "") or None,
                error=str(e),
            )
        except Exception:
            logger.debug("[操作记录] API 重命名失败记录失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"API重命名失败: {str(e)}")

def map_path_to_local(remote_path: str) -> tuple[str, bool]:
    """
    将远程路径映射到本地路径
    返回: (映射后的路径, 是否成功映射)
    """
    config = get_config()
    if not config.path_mapping.enabled:
        return remote_path, False
    
    # 统一路径分隔符为 /
    remote_path_normalized = remote_path.replace("\\", "/")
    
    for rule in config.path_mapping.rules:
        if not rule.enabled:
            continue
        
        # 统一规则路径分隔符
        rule_remote = rule.remote_path.replace("\\", "/")
        
        # 检查路径是否匹配
        if remote_path_normalized.startswith(rule_remote):
            # 替换前缀
            relative_path = remote_path_normalized[len(rule_remote):]
            # 移除开头的 / 或 \
            relative_path = relative_path.lstrip("/\\")
            
            # 组合成本地路径
            local_path = os.path.join(rule.local_path, relative_path)
            return local_path, True
    
    return remote_path, False


def _robust_rmtree(path: str, retries: int = 3, delay: float = 1.0) -> None:
    """删除目录树，自动处理只读文件(WinError 5)和文件被占用(WinError 32)。"""
    import stat

    def _onerror(func, fpath, exc_info):
        exc = exc_info[1]
        if getattr(exc, 'winerror', None) == 5:
            try:
                os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
                func(fpath)
                return
            except Exception:
                pass
        raise exc

    import time as _time
    last_exc = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except Exception as exc:
            last_exc = exc
            if getattr(exc, 'winerror', None) == 32 and attempt < retries - 1:
                _time.sleep(delay)
                continue
            break
    if last_exc:
        raise last_exc


def _is_path_under_base(path: str, base_path: str) -> bool:
    try:
        if not path or not base_path:
            return False
        target = os.path.abspath(os.path.normpath(path))
        base = os.path.abspath(os.path.normpath(base_path))
        if os.name == "nt":
            target = os.path.normcase(target)
            base = os.path.normcase(base)
        return os.path.commonpath([base, target]) == base
    except Exception:
        return False


@app.post("/api/library/delete")
async def delete_library_file(request: Request):
    """删除库内文件或文件夹（需要确认）"""
    try:
        data = await request.json()
        file_path = data.get("path")
        confirmed = data.get("confirmed", False)
        
        if not file_path:
            raise HTTPException(status_code=400, detail="缺少文件路径")
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 安全检查：确保在库目录内
        config = get_config()
        library_path = config.storage.library_path
        if not file_path.startswith(library_path):
            raise HTTPException(status_code=403, detail="只能删除库内的文件")
        
        if not confirmed:
            # 返回需要确认的信息
            import shutil
            if os.path.isdir(file_path):
                # 计算文件夹大小
                _fp_for_size = file_path
                def _calc_dir_size():
                    _sz = 0
                    for _dp, _dn, _fn in os.walk(_fp_for_size):
                        for _f in _fn:
                            try:
                                _sz += os.path.getsize(os.path.join(_dp, _f))
                            except Exception:
                                pass
                    return _sz
                total_size = await asyncio.to_thread(_calc_dir_size)
                return {
                    "need_confirm": True,
                    "type": "folder",
                    "name": os.path.basename(file_path),
                    "path": file_path,
                    "size": total_size
                }
            else:
                return {
                    "need_confirm": True,
                    "type": "file",
                    "name": os.path.basename(file_path),
                    "path": file_path,
                    "size": os.path.getsize(file_path)
                }
        
        # 执行删除
        if os.path.isdir(file_path):
            _robust_rmtree(file_path)
            logger.info(f"删除文件夹: {file_path}")
        else:
            os.remove(file_path)
            logger.info(f"删除文件: {file_path}")
        
        return {"message": "删除成功", "path": file_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

# 批量删除 API
@app.post("/api/library/batch-delete")
async def batch_delete_library_items(request: Request):
    """批量删除库内文件或文件夹"""
    try:
        data = await request.json()
        paths = data.get("paths", [])
        confirmed = data.get("confirmed", False)
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        
        # 安全检查
        config = get_config()
        library_path = config.storage.library_path
        
        for path in paths:
            if not path.startswith(library_path):
                raise HTTPException(status_code=403, detail="只能删除库内的文件")
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"路径不存在：{path}")
        
        if not confirmed:
            # 返回需要确认的信息
            import shutil
            total_count = len(paths)

            _paths_snap = list(paths)
            def _calc_total_size():
                _sz = 0
                for _path in _paths_snap:
                    if os.path.isdir(_path):
                        for _dp, _dn, _fn in os.walk(_path):
                            for _f in _fn:
                                try:
                                    _sz += os.path.getsize(os.path.join(_dp, _f))
                                except Exception:
                                    pass
                    else:
                        try:
                            _sz += os.path.getsize(_path)
                        except Exception:
                            pass
                return _sz
            total_size = await asyncio.to_thread(_calc_total_size)
            
            return {
                "need_confirm": True,
                "total_count": total_count,
                "total_size": total_size
            }
        
        # 执行删除
        success_count = 0
        failed_paths = []
        
        for path in paths:
            try:
                if os.path.isdir(path):
                    _robust_rmtree(path)
                    logger.info(f"批量删除 - 删除文件夹：{path}")
                else:
                    os.remove(path)
                    logger.info(f"批量删除 - 删除文件：{path}")
                success_count += 1
            except Exception as e:
                logger.error(f"批量删除失败：{path}, {e}")
                failed_paths.append({"path": path, "error": str(e)})
        
        return {
            "message": f"批量删除完成",
            "success_count": success_count,
            "failed_paths": failed_paths
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量删除失败：{str(e)}")


# 批量 API 重命名 API
@app.post("/api/library/batch-api-rename")
async def batch_api_rename_library_items(request: Request, background_tasks: BackgroundTasks):
    """批量 API重命名（异步处理）"""
    try:
        data = await request.json()
        paths = data.get("paths", [])
        library_id = data.get("library_id")
        
        if not paths:
            raise HTTPException(status_code=400, detail="路径列表不能为空")
        
        # 验证路径
        for path in paths:
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail=f"路径不存在：{path}")
        
        # 创建任务 ID
        import uuid
        batch_id = str(uuid.uuid4())
        
        # 在后台处理
        async def process_batch():
            from ..core.task_engine import Task, TaskType
            from ..core.metadata_service import MetadataService
            from ..core.rename_service import RenameService
            from ..core.activity_log_service import log_api_rename_action, log_batch_api_rename_result
            
            results = []
            for path in paths:
                path = str(path or "").strip()
                child_rjcode = ""
                old_name = os.path.basename(path) if path else ""
                new_name = ""
                try:
                    # 提取 RJ 号
                    rj_match = re.search(r'[RVB]J\d{6,8}', os.path.basename(path), re.IGNORECASE)
                    if not rj_match:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error="无法提取 RJ 号",
                        )
                        results.append({
                            "path": path,
                            "success": False,
                            "error": "无法提取 RJ 号"
                        })
                        continue
                    
                    rjcode = rj_match.group(0).upper()
                    child_rjcode = rjcode
                    
                    # 创建临时任务
                    temp_task = Task(task_type=TaskType.METADATA, source_path=path)
                    
                    # 获取元数据
                    metadata_service = MetadataService()
                    metadata = await metadata_service.fetch(path, temp_task)
                    
                    # 生成新名称
                    rename_service = RenameService()
                    config = get_config()
                    
                    if config.rename.api_rename_follow_template:
                        japanese_metadata = None
                        if config.rename.use_japanese_metadata:
                            japanese_metadata = await rename_service._get_japanese_metadata(rjcode)
                        new_name = rename_service._compile_name(metadata, japanese_metadata)
                        new_name = rename_service._sanitize_filename(new_name)
                    else:
                        work_name = metadata.get('work_name', '')
                        def sanitize_filename(name):
                            name = re.sub(r'[<>:"/\\|?*]', '_', name)
                            name = re.sub(r'[\x00-\x1f\x7f]', '', name)
                            name = name.rstrip(' .')
                            return name
                        new_name = f"{rjcode} {sanitize_filename(work_name)}"
                    
                    # 执行重命名
                    parent_dir = os.path.dirname(path)
                    new_path = os.path.join(parent_dir, new_name)
                    
                    if os.path.exists(new_path) and new_path != path:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error="新名称已存在",
                        )
                        results.append({
                            "path": path,
                            "success": False,
                            "error": "新名称已存在"
                        })
                    elif new_path == path:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=True,
                            source_path=path,
                            new_path=new_path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            extra_detail={"no_change": True},
                        )
                        results.append({
                            "path": path,
                            "success": True,
                            "message": "名称已是最新",
                            "new_name": new_name
                        })
                    else:
                        os.rename(path, new_path)
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=True,
                            source_path=path,
                            new_path=new_path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                        )
                        results.append({
                            "path": path,
                            "success": True,
                            "new_path": new_path,
                            "new_name": new_name
                        })
                    
                except Exception as e:
                    logger.error(f"批量 API 重命名失败：{path}, {e}")
                    try:
                        log_api_rename_action(
                            action="batch_api_rename_item",
                            success=False,
                            source_path=path,
                            old_name=old_name,
                            new_name=new_name,
                            rjcode=child_rjcode or None,
                            batch_id=batch_id,
                            library_id=str(library_id or "") or None,
                            error=str(e),
                        )
                    except Exception:
                        logger.debug("[操作记录] 批量 API 重命名子项失败记录失败", exc_info=True)
                    results.append({
                        "path": path,
                        "success": False,
                        "error": str(e)
                    })
            
            # 保存结果（可选：保存到文件或数据库）
            logger.info(f"批量 API重命名完成：batch_id={batch_id}, success={sum(1 for r in results if r['success'])}/{len(results)}")
            try:
                log_batch_api_rename_result(
                    batch_id=batch_id,
                    total_count=len(paths),
                    success_count=sum(1 for r in results if r.get('success')),
                    failed_count=sum(1 for r in results if not r.get('success')),
                    results=results,
                    source_path=str(paths[0] or "").strip() if paths else "",
                )
            except Exception:
                logger.debug("[操作记录] 批量 API 重命名汇总记录失败", exc_info=True)
        
        background_tasks.add_task(process_batch)
        
        return {
            "batch_id": batch_id,
            "message": f"已创建批量重命名任务，共 {len(paths)} 项",
            "total_count": len(paths)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量 API 重命名失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量重命名失败：{str(e)}")


@app.post("/api/library/open-folder")
async def open_library_folder(request: Request):
    """打开文件夹位置"""
    try:
        data = await request.json()
        path = data.get("path")
        force_local = data.get("force_local", False)  # 是否强制使用本地映射
        
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        # 检查路径映射配置
        config = get_config()
        mapped_path, is_mapped = map_path_to_local(path)
        
        # 判断打开模式
        open_mode = config.path_mapping.open_mode
        if force_local or open_mode == "mapped":
            # 使用映射路径打开
            target_path = mapped_path
            # 在映射模式下，不检查路径是否存在（因为后端无法访问客户端路径）
            logger.info(f"使用映射路径打开: {path} -> {target_path}")
            
            return {
                "message": "请使用本地路径打开",
                "mode": "mapped",
                "original_path": path,
                "mapped_path": target_path,
                "is_mapped": is_mapped
            }
        
        # 直接模式：后端直接打开（同设备部署）
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="路径不存在")
        
        # 获取文件夹路径（如果是文件，则获取所在文件夹）
        folder_path = path if os.path.isdir(path) else os.path.dirname(path)
        
        # 根据操作系统打开文件夹
        import platform
        import subprocess
        
        system = platform.system()
        if system == "Windows":
            # 使用 os.startfile 打开文件夹，更好地支持中文和特殊字符
            if os.path.isdir(path):
                # 如果是文件夹，直接打开
                os.startfile(path)
            else:
                # 如果是文件，使用 explorer /select 选中它
                # 使用字符串形式避免引号问题
                cmd = f'explorer /select,"{path}"'
                subprocess.run(cmd, shell=True, check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", "-R", path], check=True)
        else:  # Linux
            subprocess.run(["xdg-open", folder_path], check=True)
        
        return {"message": "已打开文件夹", "mode": "direct"}
        
    except Exception as e:
        logger.error(f"打开文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {str(e)}")

# 路径映射配置API
@app.get("/api/path-mapping/config")
async def get_path_mapping_config():
    """获取路径映射配置"""
    config = get_config().path_mapping
    return {
        "enabled": config.enabled,
        "open_mode": config.open_mode,
        "rules": [
            {
                "remote_path": rule.remote_path,
                "local_path": rule.local_path,
                "enabled": rule.enabled
            }
            for rule in config.rules
        ]
    }

@app.post("/api/path-mapping/config")
async def update_path_mapping_config(request: Request):
    """更新路径映射配置"""
    try:
        data = await request.json()
        config = get_config()
        
        # 更新配置
        config.path_mapping.enabled = data.get("enabled", config.path_mapping.enabled)
        config.path_mapping.open_mode = data.get("open_mode", config.path_mapping.open_mode)
        
        # 更新规则
        if "rules" in data:
            from app.config.settings import PathMappingRule
            config.path_mapping.rules = [
                PathMappingRule(**rule) for rule in data["rules"]
            ]
        
        # 保存配置
        save_config(config)
        
        return {"message": "路径映射配置已更新"}
        
    except Exception as e:
        logger.error(f"更新路径映射配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@app.post("/api/path-mapping/test")
async def test_path_mapping(request: Request):
    """测试路径映射"""
    try:
        data = await request.json()
        remote_path = data.get("path")
        
        if not remote_path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        
        mapped_path, is_mapped = map_path_to_local(remote_path)
        
        return {
            "original_path": remote_path,
            "mapped_path": mapped_path,
            "is_mapped": is_mapped
        }
        
    except Exception as e:
        logger.error(f"测试路径映射失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")

# 密码库智能清理API
@app.get("/api/password-cleanup/status")
async def get_cleanup_status():
    """获取清理服务状态"""
    service = get_cleanup_service()
    config = get_config().password_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "max_use_count": config.max_use_count,
        "preserve_days": config.preserve_days,
        "exclude_sources": config.exclude_sources,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/password-cleanup/preview")
async def preview_cleanup():
    """预览将要清理的密码（不实际删除）"""
    service = get_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/password-cleanup/run")
async def run_cleanup():
    """手动执行清理"""
    service = get_cleanup_service()
    result = await service.cleanup_passwords(dry_run=False)
    return result

@app.get("/api/password-cleanup/history")
async def get_cleanup_history(limit: int = 50):
    """获取清理历史记录"""
    service = get_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/password-cleanup/restart")
async def restart_cleanup_service():
    """重启清理服务（配置变更后调用）"""
    service = get_cleanup_service()
    await service.restart()
    return {
        "message": "密码库清理服务已重启",
        "status": await get_cleanup_status()
    }

# 已处理压缩包智能清理API
@app.get("/api/processed-archive-cleanup/status")
async def get_archive_cleanup_status():
    """获取已处理压缩包清理服务状态"""
    service = get_processed_archive_cleanup_service()
    config = get_config().processed_archive_cleanup

    return {
        "enabled": config.enabled,
        "is_running": service.is_running(),
        "cron_expression": config.cron_expression,
        "strategy": config.strategy,
        "preserve_days": config.preserve_days,
        "max_count": config.max_count,
        "max_size_gb": config.max_size_gb,
        "exclude_reprocessing": config.exclude_reprocessing,
        "next_cleanup_time": service.get_next_cleanup_time().isoformat() if service.get_next_cleanup_time() else None
    }

@app.get("/api/processed-archive-cleanup/preview")
async def preview_archive_cleanup():
    """预览将要清理的已处理压缩包（不实际删除）"""
    service = get_processed_archive_cleanup_service()
    result = await service.get_cleanup_preview()
    return result

@app.post("/api/processed-archive-cleanup/run")
async def run_archive_cleanup():
    """手动执行已处理压缩包清理"""
    service = get_processed_archive_cleanup_service()
    result = await service.cleanup_archives(dry_run=False)
    return result

@app.get("/api/processed-archive-cleanup/history")
async def get_archive_cleanup_history(limit: int = 50):
    """获取已处理压缩包清理历史记录"""
    service = get_processed_archive_cleanup_service()
    history = await service.get_cleanup_history(limit=limit)
    return {
        "history": history,
        "total": len(history)
    }

@app.post("/api/processed-archive-cleanup/restart")
async def restart_archive_cleanup_service():
    """重启已处理压缩包清理服务（配置变更后调用）"""
    service = get_processed_archive_cleanup_service()
    await service.restart()
    return {
        "message": "已处理压缩包清理服务已重启",
        "status": await get_archive_cleanup_status()
    }

# ========== 已存在文件夹处理 API ==========

class ExistingFolderResponse(BaseModel):
    """已存在文件夹响应模型"""
    name: str
    path: str
    rjcode: Optional[str]
    modified_time: str
    size: int
    is_directory: bool


def _normalize_existing_folder_resolution_options(options: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    alias_map = {
        "KEEP_OLD": "SKIP",
        "KEEP_BOTH": "MERGE",
        "MERGE_LANG": "MERGE",
    }
    label_map = {
        "KEEP_NEW": "保留新版",
        "MERGE": "合并",
        "SKIP": "跳过",
    }
    description_map = {
        "KEEP_NEW": "采用当前新目录作为最终结果，并在确认后替换已存在目录",
        "MERGE": "进入文件级对比视图，按文件决定保留新旧内容后生成最终目录",
        "SKIP": "放弃当前目录，保持已有目录不变并删除当前待处理目录",
    }

    for option in options or []:
        action = alias_map.get(str(option.get("action") or "").strip().upper(), str(option.get("action") or "").strip().upper())
        if action not in {"KEEP_NEW", "MERGE", "SKIP"} or action in seen:
            continue
        normalized.append({
            "action": action,
            "label": label_map[action],
            "description": option.get("description") or description_map[action],
            "recommend": bool(option.get("recommend")),
        })
        seen.add(action)

    if normalized:
        return normalized

    return [
        {
            "action": "KEEP_NEW",
            "label": "保留新版",
            "description": description_map["KEEP_NEW"],
            "recommend": True,
        },
        {
            "action": "MERGE",
            "label": "合并",
            "description": description_map["MERGE"],
            "recommend": False,
        },
        {
            "action": "SKIP",
            "label": "跳过",
            "description": description_map["SKIP"],
            "recommend": False,
        },
    ]


async def _resolve_existing_folder_conflict_path(folder_path: str, preferred_path: str | None = None) -> str | None:
    if preferred_path and os.path.exists(preferred_path):
        return preferred_path

    from ..core.duplicate_service import get_duplicate_service

    folder_name = os.path.basename(folder_path)
    rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
    rjcode = rj_match.group(0).upper() if rj_match else None
    if not rjcode:
        return None

    duplicate_service = get_duplicate_service()
    check_result = await duplicate_service.check_duplicate_enhanced(
        rjcode,
        check_linked_works=True,
        cue_languages=["CHI_HANS", "CHI_HANT", "ENG"],
    )
    if check_result.direct_duplicate:
        return check_result.direct_duplicate.get("path")
    if check_result.linked_works_found:
        return check_result.linked_works_found[0].get("path")
    return None

@app.get("/api/existing-folders", response_model=List[ExistingFolderResponse])
async def get_existing_folders():
    """获取已存在文件夹目录中的所有文件夹"""
    try:
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        # 如果目录不存在，返回空列表
        if not os.path.exists(existing_folders_path):
            return []
        
        folders = []
        for item in os.listdir(existing_folders_path):
            item_path = os.path.join(existing_folders_path, item)
            
            # 跳过隐藏文件和非文件夹项目
            if item.startswith('.') or not os.path.isdir(item_path):
                continue
            
            try:
                stat = os.stat(item_path)
                # 提取RJ号
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                # 计算文件夹大小（简化版，只统计直接子项）
                size = 0
                try:
                    for subitem in os.listdir(item_path):
                        subitem_path = os.path.join(item_path, subitem)
                        if os.path.isfile(subitem_path):
                            size += os.path.getsize(subitem_path)
                except:
                    pass
                
                folders.append(ExistingFolderResponse(
                    name=item,
                    path=item_path,
                    rjcode=rjcode,
                    modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    size=size,
                    is_directory=True
                ))
            except Exception as e:
                logger.warning(f"获取文件夹信息失败: {item_path}, {e}")
        
        # 按修改时间排序（最新的在前）
        folders.sort(key=lambda x: x.modified_time, reverse=True)
        
        return folders
        
    except Exception as e:
        logger.error(f"获取已存在文件夹列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")

@app.post("/api/existing-folders/scan")
async def scan_existing_folders(check_duplicates: bool = True, force_refresh: bool = False):
    """扫描已存在文件夹目录，先快速列出所有文件夹，再后台查重
    
    Args:
        check_duplicates: 是否执行查重检查
        force_refresh: 是否强制刷新缓存
    """
    async def generate_folders():
        try:
            config = get_config()
            existing_folders_path = config.storage.existing_folders_path
            
            # 自动创建目录（如果不存在）
            if not os.path.exists(existing_folders_path):
                try:
                    os.makedirs(existing_folders_path, exist_ok=True)
                    logger.info(f"自动创建已存在文件夹目录: {existing_folders_path}")
                except Exception as e:
                    yield json.dumps({"error": f"无法创建目录: {str(e)}"}) + "\n"
                    return
            
            # 第一步：快速列出所有文件夹（不查重）
            items = os.listdir(existing_folders_path)
            folders = []
            
            yield json.dumps({
                "type": "start",
                "total": len(items),
                "message": f"开始扫描，共 {len(items)} 个项目"
            }) + "\n"
            
            # 先发送所有文件夹基本信息（立即可见）
            for index, item in enumerate(items):
                item_path = os.path.join(existing_folders_path, item)
                
                # 跳过隐藏文件和非文件夹项目
                if item.startswith('.') or not os.path.isdir(item_path):
                    continue
                
                # 提取RJ号
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', item, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                folder_info = {
                    "name": item,
                    "path": item_path,
                    "rjcode": rjcode,
                    "status": "pending"  # 待检查状态
                }
                
                folders.append(folder_info)
                
                # 立即发送，让前端显示
                yield json.dumps({
                    "type": "folder",
                    "index": index,
                    "total": len(items),
                    "folder": folder_info,
                    "progress": f"{index + 1}/{len(items)}"
                }) + "\n"
            
            # 第二步：后台逐个查重（如果有RJ号且需要检查）
            if check_duplicates:
                conflict_count = 0
                
                yield json.dumps({
                    "type": "checking_start",
                    "message": f"开始查重检查，共 {len(folders)} 个文件夹"
                }) + "\n"
                
                # 获取数据库会话
                from ..models.database import get_db
                db = next(get_db())
                
                try:
                    for index, folder_info in enumerate(folders):
                        item_path = folder_info["path"]
                        item = folder_info["name"]
                        rjcode = folder_info["rjcode"]
                        
                        if not rjcode:
                            continue
                        
                        # 检查缓存
                        cache = None
                        if not force_refresh:
                            try:
                                from ..models.database import ExistingFolderCache
                                cache = db.query(ExistingFolderCache).filter(
                                    ExistingFolderCache.folder_path == item_path
                                ).first()
                            except Exception as e:
                                logger.warning(f"查询缓存失败: {e}")
                        
                        # 如果有缓存且不需要刷新，直接使用缓存
                        if cache and not force_refresh and not cache.needs_refresh:
                            folder_info["duplicate_info"] = cache.duplicate_info
                            folder_info["file_count"] = cache.file_count
                            folder_info["folder_size"] = cache.folder_size
                            folder_info["status"] = "cached"
                            if cache.duplicate_info:
                                conflict_count += 1
                            
                            # 发送更新
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": True
                            }) + "\n"
                            continue
                        
                        # 没有缓存，执行API查询
                        try:
                            from ..core.duplicate_service import get_duplicate_service
                            duplicate_service = get_duplicate_service()
                            
                            # 添加延时避免429
                            if index > 0 and index % 5 == 0:
                                await asyncio.sleep(1)
                            
                            check_result = await duplicate_service.check_duplicate_enhanced(
                                rjcode, 
                                check_linked_works=True,
                                cue_languages=['CHI_HANS', 'CHI_HANT', 'ENG']
                            )
                            
                            if check_result.is_duplicate:
                                folder_info["duplicate_info"] = {
                                    "is_duplicate": True,
                                    "conflict_type": check_result.conflict_type,
                                    "direct_duplicate": check_result.direct_duplicate,
                                    "linked_works_found": check_result.linked_works_found,
                                    "related_rjcodes": check_result.related_rjcodes,
                                    "analysis_info": check_result.analysis_info
                                }
                                
                                # 获取推荐的解决选项
                                resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                                folder_info["duplicate_info"]["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)
                                conflict_count += 1
                            
                            folder_info["status"] = "checked"
                            
                            # 计算文件夹大小
                            folder_size = 0
                            file_count = 0
                            try:
                                for root, dirs, files in os.walk(item_path):
                                    file_count += len(files)
                                    for file in files:
                                        file_path = os.path.join(root, file)
                                        if os.path.isfile(file_path):
                                            folder_size += os.path.getsize(file_path)
                            except:
                                pass
                            
                            folder_info["file_count"] = file_count
                            folder_info["folder_size"] = folder_size
                            
                            # 保存到缓存
                            try:
                                from ..models.database import ExistingFolderCache
                                if cache:
                                    cache.duplicate_info = folder_info.get("duplicate_info")
                                    cache.file_count = file_count
                                    cache.folder_size = folder_size
                                    cache.updated_at = datetime.now()
                                    cache.needs_refresh = False
                                else:
                                    cache = ExistingFolderCache(
                                        folder_path=item_path,
                                        folder_name=item,
                                        rjcode=rjcode,
                                        duplicate_info=folder_info.get("duplicate_info"),
                                        file_count=file_count,
                                        folder_size=folder_size
                                    )
                                    db.add(cache)
                                db.commit()
                            except Exception as e:
                                logger.warning(f"保存缓存失败: {e}")
                                db.rollback()
                            
                            # 发送更新
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "from_cache": False
                            }) + "\n"
                            
                        except Exception as e:
                            logger.warning(f"查重检查失败 {rjcode}: {e}")
                            folder_info["status"] = "error"
                            yield json.dumps({
                                "type": "folder_update",
                                "index": index,
                                "folder": folder_info,
                                "error": str(e)
                            }) + "\n"
                
                finally:
                    db.close()
                
                # 发送完成消息
                yield json.dumps({
                    "type": "complete",
                    "count": len(folders),
                    "conflict_count": conflict_count,
                    "folders": folders,
                    "message": f"扫描完成，找到 {len(folders)} 个文件夹" + (f"，其中 {conflict_count} 个可能有冲突" if conflict_count > 0 else "")
                }) + "\n"
            else:
                # 不检查重复，直接完成
                yield json.dumps({
                    "type": "complete",
                    "count": len(folders),
                    "conflict_count": 0,
                    "folders": folders,
                    "message": f"扫描完成，找到 {len(folders)} 个文件夹"
                }) + "\n"
            
        except Exception as e:
            logger.error(f"扫描已存在文件夹目录失败: {e}", exc_info=True)
            yield json.dumps({"type": "error", "error": f"扫描失败: {str(e)}"}) + "\n"
    
    return StreamingResponse(
        generate_folders(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/existing-folders/refresh-cache")
async def refresh_existing_folders_cache():
    """刷新所有已有文件夹的缓存信息"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 标记所有缓存需要刷新
            db.query(ExistingFolderCache).update({"needs_refresh": True})
            db.commit()
            
            return {"message": "已标记所有缓存需要刷新，下次扫描时将重新获取信息"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"刷新缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"刷新缓存失败: {str(e)}")

@app.post("/api/existing-folders/clear-cache")
async def clear_existing_folders_cache():
    """清除所有已有文件夹的缓存"""
    try:
        from ..models.database import get_db, ExistingFolderCache
        
        db = next(get_db())
        try:
            # 删除所有缓存
            deleted_count = db.query(ExistingFolderCache).delete()
            db.commit()
            
            return {"message": f"已清除 {deleted_count} 条缓存"}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"清除缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/existing-folders/check-duplicates")
async def check_existing_folders_duplicates(request: Request):
    """批量检查已有文件夹的查重情况
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "check_linked_works": true,
        "cue_languages": ["CHI_HANS", "CHI_HANT", "ENG"]
    }
    """
    try:
        data = await request.json()
        folder_paths = data.get("folders", [])
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT", "ENG"])
        
        if not folder_paths:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        from ..core.duplicate_service import get_duplicate_service
        duplicate_service = get_duplicate_service()
        
        results = []
        for folder_path in folder_paths:
            # 提取RJ号
            folder_name = os.path.basename(folder_path)
            rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
            rjcode = rj_match.group(0).upper() if rj_match else None
            
            if not rjcode:
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": None,
                    "error": "无法提取RJ号"
                })
                continue
            
            try:
                check_result = await duplicate_service.check_duplicate_enhanced(
                    rjcode,
                    check_linked_works=check_linked,
                    cue_languages=cue_languages
                )
                
                result = {
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "is_duplicate": check_result.is_duplicate,
                    "conflict_type": check_result.conflict_type,
                }
                
                if check_result.is_duplicate:
                    result.update({
                        "direct_duplicate": check_result.direct_duplicate,
                        "linked_works_found": check_result.linked_works_found,
                        "related_rjcodes": check_result.related_rjcodes,
                        "analysis_info": check_result.analysis_info
                    })
                    
                    # 获取推荐的解决选项
                    resolution_options = await duplicate_service.get_conflict_resolution_options(check_result)
                    result["resolution_options"] = _normalize_existing_folder_resolution_options(resolution_options)
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"查重检查失败 {rjcode}: {e}")
                results.append({
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "rjcode": rjcode,
                    "error": str(e)
                })
        
        # 统计
        duplicate_count = sum(1 for r in results if r.get("is_duplicate"))
        
        return {
            "message": f"检查完成，发现 {duplicate_count}/{len(results)} 个冲突",
            "total": len(results),
            "duplicate_count": duplicate_count,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")

@app.post("/api/existing-folders/process")
async def process_existing_folders(request: Request):
    """处理选中的已存在文件夹
    
    请求体格式：
    {
        "folders": ["/path/to/folder1", "/path/to/folder2"],
        "auto_classify": true
    }
    """
    try:
        from ..core.activity_log_service import log_import_batch_start_result
        data = await request.json()
        folders = data.get("folders", [])
        auto_classify = data.get("auto_classify", True)
        
        if not folders:
            raise HTTPException(status_code=400, detail="未选择任何文件夹")
        
        # 验证所有路径是否有效
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        valid_folders = []
        for folder_path in folders:
            # 安全检查：确保路径在 existing_folders_path 目录下
            if not _is_path_under_base(folder_path, existing_folders_path):
                logger.warning(f"路径不在已存在文件夹目录下，跳过: {folder_path}")
                continue
            
            if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
                logger.warning(f"路径不存在或不是文件夹，跳过: {folder_path}")
                continue
            
            valid_folders.append(folder_path)
        
        if not valid_folders:
            raise HTTPException(status_code=400, detail="没有有效的文件夹可以处理")
        
        # 创建处理任务
        engine = get_task_engine()
        created_tasks = []
        batch_id = str(uuid.uuid4())

        for folder_path in valid_folders:
            folder_name = os.path.basename(str(folder_path).rstrip("\\/"))
            rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
            inferred_rjcode = rj_match.group(0).upper() if rj_match else None
            task = Task(
                task_type=TaskType.PROCESS_EXISTING_FOLDER,
                source_path=folder_path,
                auto_classify=auto_classify,
                metadata={
                    "batch_id": batch_id,
                    "session_id": batch_id,
                    "batch_title": "批量已有目录处理",
                    "batch_label": "已有目录处理批次",
                    "batch_requested_count": len(valid_folders),
                    "batch_log_parent": True,
                    "source_page": "existing-folders",
                    "source_action": "process_existing_batch",
                    "source_label": "已有目录页 / 批量处理",
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "inferred_rjcode": inferred_rjcode,
                    "rjcode": inferred_rjcode,
                    "auto_classify": bool(auto_classify),
                }
            )
            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "folder_path": folder_path
            })

        log_import_batch_start_result(
            {
                "batch_id": batch_id,
                "requested_count": len(valid_folders),
                "created_count": len(created_tasks),
                "skipped_total": max(0, len(folders) - len(valid_folders)),
                "archive_count": 0,
                "extracted_count": 0,
                "auto_classify": bool(auto_classify),
                "source_page": "existing-folders",
                "source_action": "process_existing_batch",
                "source_label": "已有目录页 / 批量处理",
                "source_paths": valid_folders,
                "created_tasks": created_tasks,
                "skipped_items": [
                    {"folder_path": folder_path, "reason": "invalid_path"}
                    for folder_path in folders
                    if folder_path not in valid_folders
                ],
                "source_path": valid_folders[0] if valid_folders else None,
            },
            category="process_existing",
        )

        return {
            "message": f"已创建 {len(created_tasks)} 个处理任务",
            "requested": len(folders),
            "created": len(created_tasks),
            "batch_id": batch_id,
            "tasks": created_tasks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理已存在文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@app.post("/api/existing-folders/delete")
async def delete_existing_folder(request: Request):
    """删除已有文件夹（用于抛弃新版）
    
    请求体格式：
    {
        "path": "/path/to/folder"
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("path")
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        if not _is_path_under_base(folder_path, existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录下")
        
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        
        # 删除文件夹
        import shutil
        _robust_rmtree(folder_path)
        logger.info(f"已删除文件夹: {folder_path}")
        
        return {"message": "文件夹已删除", "path": folder_path}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@app.post("/api/existing-folders/merge-preview")
async def get_existing_folder_merge_preview(request: Request):
    """生成已存在文件夹的合并对比预览"""
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        existing_path = data.get("existing_path")

        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供待处理文件夹路径")

        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        if not _is_path_under_base(folder_path, existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录中")
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="待处理文件夹不存在")

        resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, existing_path)
        if not resolved_existing_path:
            raise HTTPException(status_code=404, detail="未找到可合并的现有目录")
        if not os.path.exists(resolved_existing_path):
            raise HTTPException(status_code=404, detail="目标现有目录不存在")

        from ..core.folder_compare_service import get_folder_compare_service

        compare_service = get_folder_compare_service()
        items = compare_service.build_compare_items(folder_path, resolved_existing_path)
        decisions = compare_service.build_default_decisions(items)

        summary = {
            "new_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "new_only"),
            "old_only": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "old_only"),
            "modified": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "modified"),
            "unchanged": sum(1 for item in items if item.get("type") == "file" and item.get("status") == "unchanged"),
        }

        return {
            "folder_path": folder_path,
            "existing_path": resolved_existing_path,
            "items": items,
            "default_decisions": decisions,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成合并预览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成合并预览失败: {str(e)}")

@app.post("/api/existing-folders/process-with-resolution")
async def process_existing_folder_with_resolution(request: Request):
    """使用指定的解决方案处理已有文件夹
    
    请求体格式：
    {
        "folder_path": "/path/to/folder",
        "resolution": "KEEP_NEW|MERGE|SKIP",
        "auto_classify": true,
        "existing_path": "/path/to/current/library/folder",
        "merge_decisions": {"relative/path.txt": "use_new"}
    }
    """
    try:
        data = await request.json()
        folder_path = data.get("folder_path")
        resolution = data.get("resolution")
        auto_classify = data.get("auto_classify", True)
        preferred_existing_path = data.get("existing_path")
        merge_decisions = data.get("merge_decisions") or {}
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="未提供文件夹路径")
        
        if not resolution:
            raise HTTPException(status_code=400, detail="未提供解决方案")
        normalized_resolution = str(resolution).strip().upper()
        if normalized_resolution == "KEEP_OLD":
            normalized_resolution = "SKIP"
        if normalized_resolution in {"KEEP_BOTH", "MERGE_LANG"}:
            normalized_resolution = "MERGE"
        if normalized_resolution not in {"KEEP_NEW", "MERGE", "SKIP"}:
            raise HTTPException(status_code=400, detail="不支持的解决方案")
        
        # 安全检查：确保路径在 existing_folders_path 目录下
        config = get_config()
        existing_folders_path = config.storage.existing_folders_path
        
        if not _is_path_under_base(folder_path, existing_folders_path):
            raise HTTPException(status_code=400, detail="路径不在已存在文件夹目录下")
        
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=404, detail="文件夹不存在")
        
        # 根据解决方案执行不同操作
        if normalized_resolution == "SKIP":
            # 抛弃新版 - 删除文件夹
            import shutil
            _robust_rmtree(folder_path)
            logger.info(f"已抛弃新版（删除文件夹）: {folder_path}")
            return {"message": "已跳过当前目录，待处理文件夹已删除", "resolution": normalized_resolution}
        
        elif normalized_resolution in ["KEEP_NEW", "MERGE"]:
            resolved_existing_path = await _resolve_existing_folder_conflict_path(folder_path, preferred_existing_path)
            if not resolved_existing_path:
                raise HTTPException(status_code=404, detail="未找到要替换或合并的现有目录")
            if not os.path.exists(resolved_existing_path):
                raise HTTPException(status_code=404, detail="现有目录不存在")

            # 这些操作都需要创建处理任务
            from ..models.database import ConflictWork, get_db
            db = next(get_db())
            try:
                # 提取RJ号
                folder_name = os.path.basename(folder_path)
                rj_match = re.search(r'[RVB]J(\d{6}|\d{8})(?!\d)', folder_name, re.IGNORECASE)
                rjcode = rj_match.group(0).upper() if rj_match else None
                
                if rjcode:
                    # 查找对应的冲突记录并更新状态
                    conflict = db.query(ConflictWork).filter(
                        ConflictWork.rjcode == rjcode,
                        ConflictWork.status == 'PENDING'
                    ).first()
                    
                    if conflict:
                        conflict.status = normalized_resolution
                        db.commit()
                        logger.info(f"更新冲突记录状态: {rjcode} -> {normalized_resolution}")
                
                # 创建处理任务
                engine = get_task_engine()
                task = Task(
                    task_type=TaskType.PROCESS_EXISTING_FOLDER,
                    source_path=folder_path,
                    auto_classify=auto_classify,
                    metadata={
                        "existing_folder_resolution": normalized_resolution,
                        "existing_path": resolved_existing_path,
                        "merge_decisions": merge_decisions if normalized_resolution == "MERGE" else {},
                        "folder_path": folder_path,
                        "folder_name": folder_name,
                        "inferred_rjcode": rjcode,
                        "rjcode": rjcode,
                        "auto_classify": bool(auto_classify),
                    }
                )
                await engine.submit(task)
                
                return {
                    "message": f"已创建处理任务，解决方案: {normalized_resolution}",
                    "resolution": normalized_resolution,
                    "task_id": task.id,
                    "folder_path": folder_path,
                    "existing_path": resolved_existing_path,
                }
                
            finally:
                db.close()
        
        else:
            raise HTTPException(status_code=400, detail=f"未知的解决方案: {resolution}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

# ========== 关联作品查询 API（改进的查重功能）==========

@app.get("/api/linked-works/{rjcode}")
async def get_linked_works(
    rjcode: str,
    include_full_linkage: bool = True,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    获取作品的关联作品链
    
    Args:
        rjcode: RJ号
        include_full_linkage: 是否包含完整关联链（包括所有语言版本）
        cue_languages: 需要查询的语言列表，逗号分隔
    """
    from ..core.dlsite_service import get_dlsite_service
    
    try:
        service = get_dlsite_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        if include_full_linkage:
            linked_works = await service.get_full_linkage(rjcode, languages)
        else:
            linked_works = await service.get_linked_works(rjcode)
        
        # 获取翻译信息
        trans_info = await service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "translation_info": {
                "is_original": trans_info.is_original,
                "is_parent": trans_info.is_parent,
                "is_child": trans_info.is_child,
                "parent_workno": trans_info.parent_workno,
                "original_workno": trans_info.original_workno,
                "lang": trans_info.lang
            },
            "linked_works": {k: v.to_dict() for k, v in linked_works.items()},
            "total_count": len(linked_works)
        }
        
    except Exception as e:
        logger.error(f"获取关联作品失败 {rjcode}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取关联作品失败: {str(e)}")


@app.get("/api/linked-works/{rjcode}/check-library")
async def check_linked_works_in_library(
    rjcode: str,
    cue_languages: str = "CHI_HANS,CHI_HANT,ENG"
):
    """
    检查作品的关联作品是否在库中
    
    返回库中已存在的所有关联作品
    """
    from ..core.dlsite_service import get_dlsite_service
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        dlsite_service = get_dlsite_service()
        duplicate_service = get_duplicate_service()
        languages = [lang.strip() for lang in cue_languages.split(',') if lang.strip()]
        
        # 获取完整关联链
        linked_works = await dlsite_service.get_full_linkage(rjcode, languages)
        
        # 检查哪些在库中
        found_in_library = await duplicate_service._check_linked_works_in_library(
            linked_works, rjcode
        )
        
        # 获取翻译信息
        trans_info = await dlsite_service.get_translation_info(rjcode)
        
        return {
            "rjcode": rjcode,
            "is_original": trans_info.is_original,
            "is_in_library": len(found_in_library) > 0,
            "library_works": [
                {
                    "rjcode": w.rjcode,
                    "work_type": w.work_type,
                    "lang": w.lang,
                    "work_name": w.work_name,
                    "path": w.folder_path,
                    "size": w.folder_size,
                    "file_count": w.file_count
                }
                for w in found_in_library
            ],
            "total_linked": len(linked_works),
            "found_in_library": len(found_in_library)
        }
        
    except Exception as e:
        logger.error(f"检查库中关联作品失败 {rjcode}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@app.post("/api/conflicts/enhanced-check")
async def enhanced_duplicate_check(request: Request):
    """
    改进的查重检查
    
    支持检测关联作品冲突
    """
    from ..core.duplicate_service import get_duplicate_service
    
    try:
        data = await request.json()
        rjcode = data.get("rjcode")
        check_linked = data.get("check_linked_works", True)
        cue_languages = data.get("cue_languages", ["CHI_HANS", "CHI_HANT"])
        
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")
        
        service = get_duplicate_service()
        result = await service.check_duplicate_enhanced(
            rjcode, 
            check_linked_works=check_linked,
            cue_languages=cue_languages
        )
        
        # 获取推荐的解决选项
        resolution_options = _normalize_existing_folder_resolution_options(
            await service.get_conflict_resolution_options(result)
        )
        
        return {
            "is_duplicate": result.is_duplicate,
            "conflict_type": result.conflict_type,
            "direct_duplicate": result.direct_duplicate,
            "linked_works_found": result.linked_works_found,
            "related_rjcodes": result.related_rjcodes,
            "analysis_info": result.analysis_info,
            "resolution_options": resolution_options
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"改进查重检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


# ========== Kikoeru 搜索配置 API ==========

@app.get("/api/kikoeru-configs")
async def get_kikoeru_configs():
    """获取所有 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        configs = db.query(KikoeruSearchConfig).all()
        return {
            "configs": [config.to_dict() for config in configs]
        }
    finally:
        db.close()


@app.post("/api/kikoeru-configs")
async def create_kikoeru_config(request: Request):
    """创建 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    import uuid
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = KikoeruSearchConfig(
            id=str(uuid.uuid4()),
            name=data.get("name", "Kikoeru"),
            search_url_template=data.get("search_url_template", ""),
            show_url_template=data.get("show_url_template", ""),
            enabled=data.get("enabled", False),
            custom_headers=data.get("custom_headers", {})
        )
        
        db.add(config)
        db.commit()
        
        return {
            "message": "配置已创建",
            "config": config.to_dict()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"创建 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")
    finally:
        db.close()


@app.put("/api/kikoeru-configs/{config_id}")
async def update_kikoeru_config(config_id: str, request: Request):
    """更新 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    try:
        data = await request.json()
        db = next(get_db())
        
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        if "name" in data:
            config.name = data["name"]
        if "search_url_template" in data:
            config.search_url_template = data["search_url_template"]
        if "show_url_template" in data:
            config.show_url_template = data["show_url_template"]
        if "enabled" in data:
            config.enabled = data["enabled"]
        if "custom_headers" in data:
            config.custom_headers = data["custom_headers"]
        
        db.commit()
        
        return {
            "message": "配置已更新",
            "config": config.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    finally:
        db.close()


@app.delete("/api/kikoeru-configs/{config_id}")
async def delete_kikoeru_config(config_id: str):
    """删除 Kikoeru 搜索配置"""
    from ..models.database import KikoeruSearchConfig, get_db
    
    db = next(get_db())
    try:
        config = db.query(KikoeruSearchConfig).filter(
            KikoeruSearchConfig.id == config_id
        ).first()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        db.delete(config)
        db.commit()
        
        return {"message": "配置已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除 Kikoeru 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()


# ========== Kikoeru 服务器查重配置 API ==========
from ..core.kikoeru_duplicate_service import get_kikoeru_service, KikoeruDuplicateService, KikoeruCheckResult

class KikoeruServerConfig(BaseModel):
    """Kikoeru 服务器配置模型"""
    enabled: bool = False
    server_url: str = ""
    username: str = ""
    password: str = ""
    api_token: str = ""
    token_expires: int = 0
    timeout: int = 10
    cache_ttl: int = 300
    enable_fuzzy_rj_match: bool = False

@app.get("/api/kikoeru-server/config")
async def get_kikoeru_server_config():
    """获取 Kikoeru 服务器查重配置"""
    try:
        config = get_config()
        kikoeru_config = config.kikoeru_server if hasattr(config, 'kikoeru_server') else None
        
        if kikoeru_config:
            return {
                "enabled": kikoeru_config.enabled,
                "server_url": kikoeru_config.server_url,
                "username": kikoeru_config.username,
                "password": kikoeru_config.password,
                "api_token": kikoeru_config.api_token,
                "token_expires": kikoeru_config.token_expires,
                "timeout": kikoeru_config.timeout,
                "cache_ttl": kikoeru_config.cache_ttl,
                "enable_fuzzy_rj_match": bool(getattr(kikoeru_config, 'enable_fuzzy_rj_match', False)),
            }
        else:
            return {
                "enabled": False,
                "server_url": "",
                "username": "",
                "password": "",
                "api_token": "",
                "token_expires": 0,
                "timeout": 10,
                "cache_ttl": 300,
                "enable_fuzzy_rj_match": False,
            }
    except Exception as e:
        logger.error(f"获取 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")

@app.post("/api/kikoeru-server/config")
async def update_kikoeru_server_config(config: KikoeruServerConfig):
    """更新 Kikoeru 服务器查重配置（已弃用，请使用 /api/config）"""
    try:
        from ..config.settings import save_config
        
        config_to_save = {
            'kikoeru_server': {
                'enabled': config.enabled,
                'server_url': config.server_url.rstrip('/'),
                'username': config.username,
                'password': config.password,
                'api_token': config.api_token,
                'token_expires': config.token_expires,
                'timeout': config.timeout,
                'cache_ttl': config.cache_ttl,
                'enable_fuzzy_rj_match': config.enable_fuzzy_rj_match,
            }
        }
        
        save_config(config_to_save)
        
        service = get_kikoeru_service()
        service.config = service._load_config()
        
        return {
            "message": "Kikoeru 服务器配置已更新",
            "config": {
                "enabled": config.enabled,
                "server_url": config.server_url,
                "timeout": config.timeout,
                "cache_ttl": config.cache_ttl,
                "enable_fuzzy_rj_match": config.enable_fuzzy_rj_match,
            }
        }
    except Exception as e:
        logger.error(f"更新 Kikoeru 服务器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

@app.post("/api/kikoeru-server/test")
async def test_kikoeru_server_connection():
    """测试 Kikoeru 服务器连接"""
    try:
        service = get_kikoeru_service()
        result = await service.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"测试 Kikoeru 服务器连接失败: {e}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
            "latency": 0
        }

@app.post("/api/kikoeru-server/check")
async def check_kikoeru_duplicate(
    rjcode: str,
    check_linkages: bool = True,
    cue_languages: str = "CHI_HANS CHI_HANT ENG JPN"
):
    """检查作品及其关联作品是否在 Kikoeru 服务器中

    Args:
        rjcode: RJ号
        check_linkages: 是否检查关联作品
        cue_languages: 语言列表，空格分隔（如 'CHI_HANS CHI_HANT ENG JPN'）
    """
    logger.info(f"=" * 60)
    logger.info(f"[Kikoeru查重] 开始查询: {rjcode}, check_linkages={check_linkages}")

    try:
        # 解析语言列表
        lang_list = cue_languages.split() if cue_languages else ["CHI_HANS", "CHI_HANT", "ENG", "JPN"]
        logger.info(f"[Kikoeru查重] 检查语言: {lang_list}")
        
        service = get_kikoeru_service()
        
        if check_linkages:
            # 查询关联作品
            logger.info(f"[Kikoeru查重] 执行关联作品查询...")
            results = await service.check_duplicate_with_linkages(rjcode, lang_list, use_cache=True)

            # 格式化返回结果
            found_works = []
            for rj, res in results.items():
                if res.is_found:
                    matched_rjcode = str(res.matched_rjcode or rj or res.rjcode or "").strip().upper()
                    found_works.append({
                        "rjcode": rj,
                        "matched_rjcode": matched_rjcode,
                        "title": res.title,
                        "circle_name": res.circle_name,
                        "tags": res.tags,
                        "source": res.source,
                    })
            
            primary_result = results.get(rjcode, KikoeruCheckResult(rjcode=rjcode))
            matched_result = next((item for item in found_works if item.get("matched_rjcode")), None)
            
            logger.info(f"[Kikoeru查重] 关联查询完成: 总共 {len(results)} 个作品，找到 {len(found_works)} 个")
            
            return {
                "rjcode": rjcode,
                "is_found": primary_result.is_found or len(found_works) > 0,
                "matched_rjcode": (
                    primary_result.matched_rjcode
                    or (matched_result or {}).get("matched_rjcode")
                    or (matched_result or {}).get("rjcode")
                    or ""
                ),
                "title": primary_result.title,
                "circle_name": primary_result.circle_name,
                "tags": primary_result.tags,
                "primary_result": {
                    "rjcode": primary_result.rjcode,
                    "is_found": primary_result.is_found,
                    "matched_rjcode": primary_result.matched_rjcode,
                    "title": primary_result.title,
                    "circle_name": primary_result.circle_name,
                    "source": primary_result.source,
                },
                "linked_works_found": found_works,
                "total_checked": len(results),
                "source": "kikoeru_with_linkages",
                "checked_at": datetime.now().isoformat()
            }
        else:
            # 只查询单个作品
            result = await service.check_duplicate(rjcode, use_cache=True)
            
            return {
                "rjcode": result.rjcode,
                "is_found": result.is_found,
                "title": result.title,
                "circle_name": result.circle_name,
                "tags": result.tags,
                "linked_works_found": [],
                "total_checked": 1,
                "source": result.source,
                "checked_at": result.checked_at.isoformat() if result.checked_at else None
            }
    except Exception as e:
        logger.error(f"[Kikoeru查重] 查询失败: {rjcode}, 错误: {e}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"查重检查失败: {str(e)}")
    finally:
        logger.info(f"[Kikoeru查重] 查询结束: {rjcode}")
        logger.info(f"=" * 60)

@app.post("/api/kikoeru-server/clear-cache")
async def clear_kikoeru_cache():
    """清除 Kikoeru 查重缓存"""
    try:
        service = get_kikoeru_service()
        service.clear_cache()

        return {"message": "Kikoeru 查重缓存已清除"}
    except Exception as e:
        logger.error(f"清除 Kikoeru 缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@app.post("/api/kikoeru-server/get-token")
async def get_kikoeru_token():
    """手动获取 Kikoeru 服务器的 Token"""
    try:
        service = get_kikoeru_service()

        # 重新加载配置，确保使用最新的配置
        service.config = service._load_config()

        # 检查配置
        if not service.config.server_url:
            raise HTTPException(status_code=400, detail="请先配置服务器地址")

        if not service.config.username or not service.config.password:
            raise HTTPException(status_code=400, detail="请先配置用户名和密码")

        logger.info(f"[Kikoeru] 使用服务器地址: {service.config.server_url}")
        logger.info(f"[Kikoeru] 使用用户名: {service.config.username}")

        # 调用登录方法获取 Token
        success = await service._login()

        if success:
            return {
                "success": True,
                "token": service.config.api_token,
                "expires": service.config.token_expires,
                "message": "Token 获取成功"
            }
        else:
            raise HTTPException(status_code=401, detail="获取 Token 失败，请检查用户名和密码")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Kikoeru Token 失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Token 失败: {str(e)}")


# ========== ASMR 同步下载 API ==========

class RJSubtitleScanRequest(BaseModel):
    """RJ 字幕扫描请求"""
    folder_path: str
    library_id: Optional[str] = None
    scan_depth: int = 3
    scan_one_level_only: Optional[bool] = None


class RJSubtitleStartRequest(BaseModel):
    """RJ 字幕抓取开始请求"""
    items: List[dict]  # [{rjcode, folder_path, folder_name}]
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    skip_if_existing_subtitles: bool = False
    force_rerun: bool = False
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []
    batch_context: Optional[dict] = None


class RJSubtitleManualCompleteRequest(BaseModel):
    applied_pairs: int = 0
    deleted_subtitles: int = 0
    naming_strategy: str = "audio"
    pair_changes: List[dict] = []
    folder_path: str = ""
    library_id: Optional[str] = None
    rjcode: str = ""


class RJSubtitleRerunRequest(BaseModel):
    overwrite_existing: bool = False
    enable_metadata_match: bool = True
    naming_strategy: str = "audio"
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class RJSubtitleAvailabilityRequest(BaseModel):
    rjcode: str


class RJSubtitleFolderSubtitleStateRequest(BaseModel):
    folder_path: str
    library_id: Optional[str] = None


class RJSubtitleKikoeruSubtitleStateRequest(BaseModel):
    rjcode: str


class LinkedSubtitleArchivePreviewRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None


class LinkedSubtitleFolderPreviewRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    source_rjcode_hint: Optional[str] = None


class LinkedSubtitleArchiveImportRequest(BaseModel):
    archive_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitleFolderImportRequest(BaseModel):
    folder_path: str
    preferred_library_id: Optional[str] = None
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    source_rjcode_hint: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []


class LinkedSubtitlePendingImportExecuteRequest(BaseModel):
    target_library_id: Optional[str] = None
    target_folder_path: Optional[str] = None
    use_filter_rules: bool = False
    subtitle_filter_rules: List[dict] = []

class LinkedSubtitlePendingClearRequest(BaseModel):
    record_ids: List[str] = []
    clear_all: bool = False


@app.post("/api/rj-subtitle/scan")
async def rj_subtitle_scan(request: RJSubtitleScanRequest):
    """扫描单个 RJ 文件夹或批量父目录"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        folder_path = request.folder_path
        service = get_rj_subtitle_service()
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)
        if request.library_id:
            manager = get_library_manager()
            library = manager.get_library_definition(request.library_id)
            if library.type == "synology_filestation":
                items = await service.scan_remote(
                    request.library_id,
                    folder_path,
                    scan_depth=scan_depth,
                )
                return {
                    "success": True,
                    "folder_path": folder_path,
                    "total_found": len(items),
                    "ready_count": len([item for item in items if item["status"] == "ready"]),
                    "items": items,
                }
        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")
        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        items = service.scan(
            folder_path,
            scan_depth=scan_depth,
        )

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(items),
            "ready_count": len([item for item in items if item["status"] == "ready"]),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描 RJ 字幕目录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/rj-subtitle/scan-stream")
async def rj_subtitle_scan_stream(request: RJSubtitleScanRequest):
    """流式扫描 RJ 目录，发现一个就返回一个。"""
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    async def generate():
        service = get_rj_subtitle_service()
        folder_path = request.folder_path
        scan_depth = request.scan_depth
        if request.scan_one_level_only is not None:
            scan_depth = 1 if request.scan_one_level_only else max(3, scan_depth)

        total_found = 0
        ready_count = 0
        existing_count = 0
        no_audio_count = 0
        event_queue: asyncio.Queue = asyncio.Queue()

        def dump(payload):
            return json.dumps(payload, ensure_ascii=False) + "\n"

        def enqueue(payload):
            try:
                event_queue.put_nowait(payload)
            except Exception:
                logger.debug("RJ 字幕扫描流事件入队失败: %s", payload, exc_info=True)

        display_name = PurePosixPath(folder_path).name or os.path.basename(folder_path) or folder_path
        enqueue({
            "type": "target_result",
            "path": folder_path,
            "name": display_name,
            "status": "pending",
            "message": "正在扫描..."
        })

        def emit_progress(current_scan_path: str):
            current_display = PurePosixPath(current_scan_path).name or os.path.basename(current_scan_path) or current_scan_path
            enqueue({
                "type": "progress",
                "path": folder_path,
                "current_path": current_scan_path,
                "message": f"正在扫描 {current_display}..."
            })

        async def produce():
            nonlocal total_found, ready_count, existing_count, no_audio_count
            try:
                if request.library_id:
                    manager = get_library_manager()
                    library = manager.get_library_definition(request.library_id)
                    if library.type == "synology_filestation":
                        async for item in service.scan_remote_iter(
                            request.library_id,
                            folder_path,
                            scan_depth=scan_depth,
                            progress_callback=emit_progress,
                        ):
                            total_found += 1
                            if item.get("status") == "ready":
                                ready_count += 1
                            elif item.get("status") == "existing":
                                existing_count += 1
                            elif item.get("status") == "no_audio":
                                no_audio_count += 1
                            enqueue({"type": "item", "item": item})
                        enqueue({
                            "type": "target_result",
                            "path": folder_path,
                            "name": display_name,
                            "status": "success" if total_found else "no_match",
                            "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                            "summary": {
                                "found": total_found,
                                "ready": ready_count,
                                "existing": existing_count,
                                "no_audio": no_audio_count,
                            }
                        })
                        enqueue({
                            "type": "complete",
                            "folder_path": folder_path,
                            "total_found": total_found,
                            "ready_count": ready_count,
                            "existing_count": existing_count,
                            "no_audio_count": no_audio_count,
                        })
                        return

                if not os.path.exists(folder_path):
                    raise HTTPException(status_code=400, detail="指定的文件夹不存在")
                if not os.path.isdir(folder_path):
                    raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

                for item in service.scan_iter(folder_path, scan_depth=scan_depth, progress_callback=emit_progress):
                    total_found += 1
                    if item.get("status") == "ready":
                        ready_count += 1
                    elif item.get("status") == "existing":
                        existing_count += 1
                    elif item.get("status") == "no_audio":
                        no_audio_count += 1
                    enqueue({"type": "item", "item": item})

                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "success" if total_found else "no_match",
                    "message": f"识别到 {total_found} 个 RJ 目录，可执行 {ready_count} 个" if total_found else "未识别到可执行 RJ 文件夹",
                    "summary": {
                        "found": total_found,
                        "ready": ready_count,
                        "existing": existing_count,
                        "no_audio": no_audio_count,
                    }
                })
                enqueue({
                    "type": "complete",
                    "folder_path": folder_path,
                    "total_found": total_found,
                    "ready_count": ready_count,
                    "existing_count": existing_count,
                    "no_audio_count": no_audio_count,
                })
            except HTTPException as exc:
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": exc.detail,
                })
                enqueue({"type": "error", "error": exc.detail})
            except Exception as exc:
                logger.error(f"流式扫描 RJ 字幕目录失败: {exc}", exc_info=True)
                message = f"扫描失败: {str(exc)}"
                enqueue({
                    "type": "target_result",
                    "path": folder_path,
                    "name": display_name,
                    "status": "failed",
                    "message": message,
                })
                enqueue({"type": "error", "error": message})
            finally:
                enqueue({"type": "stream_end"})

        producer = asyncio.create_task(produce())
        try:
            while True:
                payload = await event_queue.get()
                if payload.get("type") == "stream_end":
                    break
                yield dump(payload)
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/rj-subtitle/start")
async def rj_subtitle_start(request: RJSubtitleStartRequest):
    """开始 RJ 字幕抓取任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine
    from ..core.rj_subtitle_service import get_rj_subtitle_service
    from ..core.activity_log_service import log_subtitle_batch_start_result

    try:
        engine = get_task_engine()
        rj_service = get_rj_subtitle_service()
        created_tasks = []
        skipped_existing = 0
        skipped_duplicate = 0
        skipped_items = []
        batch_context = request.batch_context if isinstance(request.batch_context, dict) else {}
        batch_id = str(batch_context.get("batch_id") or "").strip()
        log_parent = bool(batch_context.get("log_parent"))
        source_directories = batch_context.get("source_directories") if isinstance(batch_context.get("source_directories"), list) else []
        scan_targets = batch_context.get("scan_targets") if isinstance(batch_context.get("scan_targets"), list) else []
        should_log_batch = bool(batch_id) and log_parent

        if not request.items:
            if should_log_batch:
                summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
                recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or 0)
                skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
                log_subtitle_batch_start_result({
                    "batch_id": batch_id,
                    "requested_count": int(batch_context.get("requested_count") or 0),
                    "recognized_rj_count": recognized_rj_count,
                    "created_count": 0,
                    "skipped_total": skipped_no_subtitle,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "skipped_no_subtitle": skipped_no_subtitle,
                    "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                    "force_rerun": request.force_rerun,
                    "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                    "naming_strategy": request.naming_strategy,
                    "source_directories": source_directories,
                    "scan_targets": scan_targets,
                    "created_tasks": [],
                    "skipped_items": [],
                    "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
                })
                return {
                    "success": True,
                    "message": "本次批量扫描未命中可创建的 RJ 字幕任务",
                    "created_count": 0,
                    "skipped_existing": 0,
                    "skipped_duplicate": 0,
                    "batch_id": batch_id or None,
                    "skipped_items": [],
                    "tasks": [],
                }
            raise HTTPException(status_code=400, detail="没有可执行的 RJ 文件夹")

        for item in request.items:
            folder_path = str(item.get("folder_path") or "").strip()
            rjcode = str(item.get("rjcode") or "").strip().upper()
            folder_name = str(item.get("folder_name") or "")
            library_id = str(item.get("library_id") or "").strip() or None
            if not folder_path:
                continue

            resolved_existing_subtitle_count = int(item.get("existing_subtitle_count") or 0)
            kikoeru_state = None

            if request.skip_if_existing_subtitles and rjcode:
                try:
                    kikoeru_state = await rj_service.check_kikoeru_existing_subtitles(rjcode)
                except Exception as exc:
                    logger.warning(
                        "[RJ字幕] 查询 Kikoeru 字幕状态失败，继续后续流程: rj=%s error=%s",
                        rjcode,
                        exc,
                    )
                    kikoeru_state = None

                if kikoeru_state and bool(kikoeru_state.get("has_existing_subtitles")):
                    skipped_existing += 1
                    matched_rjcode = str(kikoeru_state.get("matched_rjcode") or rjcode).upper()
                    subtitle_file_count = int(kikoeru_state.get("subtitle_file_count") or 0)
                    queue_message = f"Kikoeru 已有字幕（{matched_rjcode}"
                    if subtitle_file_count > 0:
                        queue_message += f" / {subtitle_file_count} 个"
                    queue_message += "），未加入抓取任务"
                    skipped_items.append({
                        "rjcode": rjcode,
                        "folder_name": folder_name,
                        "folder_path": folder_path,
                        "library_id": library_id,
                        "existing_subtitle_count": resolved_existing_subtitle_count,
                        "queue_state": "skipped_kikoeru_existing",
                        "queue_message": queue_message,
                        "kikoeru_checked_rjcode": kikoeru_state.get("checked_rjcode", rjcode),
                        "kikoeru_has_work": bool(kikoeru_state.get("has_work")),
                        "kikoeru_has_existing_subtitles": True,
                        "kikoeru_matched_rjcode": matched_rjcode,
                        "kikoeru_subtitle_file_count": subtitle_file_count,
                        "kikoeru_subtitle_check_source": kikoeru_state.get("subtitle_check_source", ""),
                    })
                    continue

            duplicate_task = next((
                current_task for current_task in engine.get_all_tasks()
                if current_task.type == TaskType.RJ_SUBTITLE_FETCH
                and str(current_task.task_metadata.get("folder_path") or current_task.source_path) == str(folder_path)
                and current_task.status.value in {"pending", "processing", "paused"}
            ), None)
            if duplicate_task:
                skipped_duplicate += 1
                skipped_items.append({
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "folder_path": folder_path,
                    "library_id": library_id,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "task_id": duplicate_task.id,
                    "queue_state": "existing_task",
                    "queue_message": "任务已存在",
                })
                continue

            task = Task(
                task_type=TaskType.RJ_SUBTITLE_FETCH,
                source_path=folder_path,
                auto_classify=False,
                metadata={
                    "folder_path": folder_path,
                    "rjcode": rjcode,
                    "folder_name": folder_name,
                    "library_id": library_id,
                    "overwrite": request.overwrite_existing,
                    "enable_metadata_match": request.enable_metadata_match,
                    "skip_if_existing_subtitles": False if request.force_rerun else request.skip_if_existing_subtitles,
                    "force_rerun": request.force_rerun,
                    "existing_subtitle_count": resolved_existing_subtitle_count,
                    "naming_strategy": request.naming_strategy,
                    "use_filter_rules": request.use_filter_rules,
                    "subtitle_filter_rules": request.subtitle_filter_rules,
                    "batch_id": batch_id or None,
                    "kikoeru_checked_rjcode": (kikoeru_state or {}).get("checked_rjcode", rjcode),
                    "kikoeru_has_work": bool((kikoeru_state or {}).get("has_work")),
                    "kikoeru_has_existing_subtitles": bool((kikoeru_state or {}).get("has_existing_subtitles")),
                    "kikoeru_matched_rjcode": (kikoeru_state or {}).get("matched_rjcode", ""),
                    "kikoeru_subtitle_file_count": int((kikoeru_state or {}).get("subtitle_file_count") or 0),
                    "kikoeru_subtitle_check_source": (kikoeru_state or {}).get("subtitle_check_source", ""),
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "folder_name": folder_name,
                "folder_path": folder_path,
                "library_id": library_id,
            })

        if should_log_batch:
            summary = batch_context.get("summary") if isinstance(batch_context.get("summary"), dict) else {}
            requested_count = int(batch_context.get("requested_count") or len(request.items))
            recognized_rj_count = int(summary.get("found") or batch_context.get("recognized_rj_count") or len(request.items))
            skipped_no_subtitle = int(summary.get("skippedNoSubtitle") or summary.get("skipped_no_subtitle") or batch_context.get("skipped_no_subtitle") or 0)
            log_subtitle_batch_start_result({
                "batch_id": batch_id,
                "requested_count": requested_count,
                "recognized_rj_count": recognized_rj_count,
                "created_count": len(created_tasks),
                "skipped_total": skipped_existing + skipped_duplicate + skipped_no_subtitle,
                "skipped_existing": skipped_existing,
                "skipped_duplicate": skipped_duplicate,
                "skipped_no_subtitle": skipped_no_subtitle,
                "scan_directory_count": int(batch_context.get("scan_directory_count") or len(source_directories)),
                "force_rerun": request.force_rerun,
                "skip_if_existing_subtitles": request.skip_if_existing_subtitles,
                "naming_strategy": request.naming_strategy,
                "source_directories": source_directories,
                "scan_targets": scan_targets,
                "created_tasks": created_tasks,
                "skipped_items": skipped_items,
                "source_path": str(source_directories[0].get("folder_path") or source_directories[0].get("path") or "").strip() if source_directories else "",
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个 RJ 字幕抓取任务",
            "created_count": len(created_tasks),
            "skipped_existing": skipped_existing,
            "skipped_duplicate": skipped_duplicate,
            "batch_id": batch_id or None,
            "skipped_items": skipped_items,
            "tasks": created_tasks,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动 RJ 字幕抓取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/rj-subtitle/folder-subtitle-state")
async def rj_subtitle_folder_subtitle_state(request: RJSubtitleFolderSubtitleStateRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        folder_path = str(request.folder_path or "").strip()
        library_id = str(request.library_id or "").strip()
        if not folder_path:
            raise HTTPException(status_code=400, detail="目录路径不能为空")
        if not library_id:
            raise HTTPException(status_code=400, detail="库存 ID 不能为空")

        summary = await get_linked_subtitle_import_service().summarize_target_folder(library_id, folder_path)
        if not summary:
            raise HTTPException(status_code=404, detail="未找到目录摘要")

        return {
            "success": True,
            "folder_path": folder_path,
            "library_id": library_id,
            "has_existing_subtitles": bool(summary.get("has_existing_subtitles")),
            "existing_subtitle_count": int(summary.get("existing_subtitle_count") or 0),
            "subtitle_dir": str(summary.get("subtitle_dir") or ""),
            "audio_count": int(summary.get("audio_count") or 0),
            "ready_for_import": bool(summary.get("ready_for_import")),
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RJ 目录字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/kikoeru-subtitle-state")
async def rj_subtitle_kikoeru_subtitle_state(request: RJSubtitleKikoeruSubtitleStateRequest):
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        state = await get_rj_subtitle_service().check_kikoeru_existing_subtitles(rjcode)
        return {
            "success": True,
            **state,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Kikoeru 字幕状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/manual-complete")
async def rj_subtitle_manual_complete(
    task_id: str,
    request: RJSubtitleManualCompleteRequest,
    db: Session = Depends(get_db),
):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service
    from ..core.task_engine import TaskStatus, TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        applied_pairs = max(0, int(request.applied_pairs or 0))
        deleted_subtitles = max(0, int(request.deleted_subtitles or 0))
        fallback_folder_path = str(request.folder_path or "").strip()
        fallback_rjcode = str(request.rjcode or "").strip().upper()
        pair_changes = request.pair_changes if isinstance(request.pair_changes, list) else []
        pair_changes = pair_changes[:200]
        fallback_crawl_row = None

        if task and task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")

        if not task:
            crawl_query = (
                db.query(ActivityLog)
                .filter(ActivityLog.category == "subtitle_crawl")
                .order_by(desc(ActivityLog.created_at))
            )
            if task_id:
                fallback_crawl_row = crawl_query.filter(ActivityLog.task_id == task_id).first()
            if not fallback_crawl_row and fallback_folder_path:
                path_query = crawl_query.filter(ActivityLog.source_path == fallback_folder_path)
                if fallback_rjcode:
                    path_query = path_query.filter(ActivityLog.rjcode == fallback_rjcode)
                fallback_crawl_row = path_query.first()
            if not fallback_crawl_row and fallback_rjcode:
                fallback_crawl_row = crawl_query.filter(ActivityLog.rjcode == fallback_rjcode).first()
            if not fallback_crawl_row:
                raise HTTPException(status_code=404, detail="任务不存在，且未找到对应的字幕抓取记录")

            crawl_detail = fallback_crawl_row.detail if isinstance(fallback_crawl_row.detail, dict) else {}
            naming_strategy = str(request.naming_strategy or crawl_detail.get("naming_strategy") or "audio").lower()
            rj_log = fallback_rjcode or str(fallback_crawl_row.rjcode or "").strip().upper()
            source_path = fallback_folder_path or str(fallback_crawl_row.source_path or "").strip()
            summary_parts = [f"已应用 {applied_pairs} 组配对"]
            if deleted_subtitles:
                summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
            summary = "，".join(summary_parts)

            from ..core.activity_log_service import log_subtitle_pair_complete

            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "batch_id": str(crawl_detail.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": source_path or None,
                    "library_id": str(request.library_id or crawl_detail.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                    "manual_match_completed": True,
                },
                source_path=source_path or None,
            )
            return {
                "success": True,
                "message": summary,
                "task_id": task_id,
                "fallback_logged": True,
            }

        naming_strategy = str(request.naming_strategy or task.task_metadata.get("naming_strategy") or "audio").lower()
        linked_finalize_result = await get_linked_subtitle_import_service().finalize_manual_match_task(task)

        task.task_metadata = task.task_metadata or {}
        task.task_metadata["awaiting_manual_match"] = False
        task.task_metadata["manual_match_completed"] = True
        task.task_metadata["manual_match_completed_at"] = datetime.now().isoformat()
        task.task_metadata["manual_match_applied_pairs"] = applied_pairs
        task.task_metadata["manual_match_deleted_subtitles"] = deleted_subtitles
        task.task_metadata["naming_strategy"] = naming_strategy

        summary_parts = [f"已应用 {applied_pairs} 组配对"]
        if deleted_subtitles:
            summary_parts.append(f"删除 {deleted_subtitles} 个未使用字幕")
        if linked_finalize_result.get("applied"):
            summary_parts.append(
                f"已确认导入目标目录，共 {int(linked_finalize_result.get('final_file_count') or 0)} 个字幕"
            )
        summary = "，".join(summary_parts)

        task.progress = 100
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.current_step = summary

        logs = task.task_metadata.get("progress_log", [])
        logs.append({
            "time": datetime.now().isoformat(),
            "progress": 100,
            "level": "success",
            "message": summary,
        })
        task.task_metadata["progress_log"] = logs

        try:
            from ..core.activity_log_service import log_subtitle_pair_complete, log_subtitle_import_action

            rj_log = str(task.task_metadata.get("rjcode") or "").strip().upper()
            _lf = linked_finalize_result if isinstance(linked_finalize_result, dict) else {}
            log_subtitle_pair_complete(
                task_id,
                rj_log,
                applied_pairs,
                deleted_subtitles,
                summary,
                linked_detail={
                    "applied": _lf.get("applied"),
                    "final_file_count": _lf.get("final_file_count"),
                    "reason": _lf.get("reason"),
                    "batch_id": str(task.task_metadata.get("batch_id") or "").strip() or None,
                    "pair_changes": pair_changes,
                    "folder_path": str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
                    "library_id": str(task.task_metadata.get("library_id") or "").strip() or None,
                    "naming_strategy": naming_strategy,
                },
                source_path=str(task.task_metadata.get("folder_path") or task.source_path or "").strip() or None,
            )
            if _lf.get("applied"):
                imported_count = int(_lf.get("final_file_count") or 0)
                import_target_rj = str(
                    task.task_metadata.get("target_rjcode")
                    or task.task_metadata.get("actual_rjcode")
                    or rj_log
                    or ""
                ).strip().upper()
                import_source_path = str(
                    task.task_metadata.get("source_archive_path")
                    or task.task_metadata.get("source_subtitle_folder_path")
                    or task.source_path
                    or ""
                ).strip() or None
                import_action = (
                    "archive_import"
                    if str(task.task_metadata.get("source_mode") or "").strip() == "linked_translation_archive_import"
                    else "folder_import"
                )
                log_subtitle_import_action(
                    action=import_action,
                    success=True,
                    summary=f"字幕补配完成，共导入 {imported_count} 个字幕文件",
                    detail={
                        "task_id": task_id,
                        "final_file_count": imported_count,
                        "target_rjcode": import_target_rj or None,
                        "source_rjcode": str(task.task_metadata.get("rjcode") or "").strip().upper() or None,
                        "manual_match_completed": True,
                        "manual_match_applied_pairs": applied_pairs,
                        "manual_match_deleted_subtitles": deleted_subtitles,
                    },
                    rjcode=import_target_rj or rj_log or None,
                    task_id=task_id,
                    source_path=import_source_path,
                )
        except Exception:
            logger.warning("[操作记录] 字幕配对记录失败", exc_info=True)

        source_mode = str(task.task_metadata.get("source_mode") or "").strip().lower()
        if source_mode in {"linked_translation_archive_import", "subtitle_folder_import"}:
            try:
                engine.persist_task_snapshot(task)
            except Exception:
                logger.warning("[任务中心] 字幕补配完成后保留任务快照失败: task_id=%s", task_id, exc_info=True)
        else:
            try:
                engine.remove_task(task_id)
            except Exception:
                logger.warning("[任务中心] 字幕配对完成后清理任务记录失败: task_id=%s", task_id, exc_info=True)

        return {"success": True, "task_id": task_id, "message": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记 RJ 字幕后处理完成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"标记失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/rerun")
async def rj_subtitle_rerun_task(task_id: str, request: RJSubtitleRerunRequest):
    from ..core.task_engine import get_task_engine

    try:
        task = await get_task_engine().rerun_rj_subtitle_task(task_id, {
            "overwrite": request.overwrite_existing,
            "enable_metadata_match": request.enable_metadata_match,
            "naming_strategy": request.naming_strategy,
            "use_filter_rules": request.use_filter_rules,
            "subtitle_filter_rules": request.subtitle_filter_rules,
        })
        return {
            "success": True,
            "task_id": task.id,
            "message": "任务已重置并重新加入抓取队列"
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as e:
        logger.error(f"重跑 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重跑失败: {str(e)}")


@app.post("/api/rj-subtitle/task/{task_id}/clear")
async def rj_subtitle_clear_task(task_id: str):
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task or task.type != TaskType.RJ_SUBTITLE_FETCH:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status.value in {"pending", "processing", "paused"}:
            raise HTTPException(status_code=400, detail="任务仍在执行中，不能清理")

        engine.remove_task(task_id)
        return {"success": True, "task_id": task_id, "message": "任务已清理"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理 RJ 字幕任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@app.post("/api/rj-subtitle/subtitle-availability")
async def rj_subtitle_availability(request: RJSubtitleAvailabilityRequest):
    from ..core.rj_subtitle_service import get_rj_subtitle_service

    try:
        rjcode = str(request.rjcode or "").strip().upper()
        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        service = get_rj_subtitle_service()
        source, attempts = await service.find_best_subtitle_source(rjcode)

        return {
            "success": True,
            "rjcode": rjcode,
            "has_subtitle": bool(source),
            "selected_source": {
                "rjcode": source.get("rjcode", ""),
                "lang": source.get("lang", ""),
                "work_type": source.get("work_type", ""),
                "title": source.get("title", ""),
                "subtitle_count": len(source.get("subtitle_files", []) or []),
            } if source else None,
            "attempts": attempts,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检测 RJ 字幕可用性失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@app.get("/api/rj-subtitle/status")
async def rj_subtitle_status():
    """获取 RJ 字幕抓取任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()
        rj_tasks = [task for task in all_tasks if task.type == TaskType.RJ_SUBTITLE_FETCH]
        status_weight = {
            "processing": 0,
            "pending": 1,
            "paused": 2,
            "completed": 3,
            "failed": 4,
        }
        rj_tasks.sort(
            key=lambda task: (
                status_weight.get(task.status.value, 99),
                -(task.created_at.timestamp() if task.created_at else 0),
            )
        )

        return {
            "total_tasks": len(rj_tasks),
            "processing": len([task for task in rj_tasks if task.status.value == "processing"]),
            "pending": len([task for task in rj_tasks if task.status.value == "pending"]),
            "completed": len([task for task in rj_tasks if task.status.value == "completed"]),
            "failed": len([task for task in rj_tasks if task.status.value == "failed"]),
            "tasks": [
                {
                    "id": task.id,
                    "rjcode": task.task_metadata.get("rjcode", ""),
                    "actual_rjcode": task.task_metadata.get("actual_rjcode", ""),
                    "folder_name": task.task_metadata.get("folder_name", ""),
                    "folder_path": task.task_metadata.get("folder_path", task.source_path),
                    "library_id": task.task_metadata.get("library_id", ""),
                    "status": task.status.value,
                    "is_cancelled": task.is_cancelled(),
                    "progress": task.progress,
                    "current_step": task.current_step,
                    "error_message": task.error_message,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "source_lang": task.task_metadata.get("source_lang", ""),
                    "source_work_type": task.task_metadata.get("source_work_type", ""),
                    "source_title": task.task_metadata.get("source_title", ""),
                    "source_mode": task.task_metadata.get("source_mode", ""),
                    "target_rjcode": task.task_metadata.get("target_rjcode", ""),
                    "target_folder_path": task.task_metadata.get("target_folder_path", ""),
                    "target_library_id": task.task_metadata.get("target_library_id", ""),
                    "subtitle_library_id": task.task_metadata.get("subtitle_library_id", task.task_metadata.get("library_id", "")),
                    "source_archive_path": task.task_metadata.get("source_archive_path", ""),
                    "source_subtitle_folder_path": task.task_metadata.get("source_subtitle_folder_path", ""),
                    "import_reason": task.task_metadata.get("import_reason", ""),
                    "kikoeru_checked_rjcode": task.task_metadata.get("kikoeru_checked_rjcode", ""),
                    "kikoeru_has_work": task.task_metadata.get("kikoeru_has_work", False),
                    "kikoeru_has_existing_subtitles": task.task_metadata.get("kikoeru_has_existing_subtitles", False),
                    "kikoeru_matched_rjcode": task.task_metadata.get("kikoeru_matched_rjcode", ""),
                    "kikoeru_subtitle_file_count": task.task_metadata.get("kikoeru_subtitle_file_count", 0),
                    "kikoeru_subtitle_check_source": task.task_metadata.get("kikoeru_subtitle_check_source", ""),
                    "downloaded_count": task.task_metadata.get("downloaded_count", 0),
                    "existing_subtitle_count": task.task_metadata.get("existing_subtitle_count", 0),
                    "subtitle_dir": task.task_metadata.get("subtitle_dir", ""),
                    "written_files": task.task_metadata.get("written_files", []),
                    "skipped_files": task.task_metadata.get("skipped_files", []),
                    "write_errors": task.task_metadata.get("write_errors", []),
                    "failed_files": task.task_metadata.get("failed_files", []),
                    "match_result": task.task_metadata.get("match_result", {}),
                    "search_attempts": task.task_metadata.get("search_attempts", []),
                    "download_files": task.task_metadata.get("download_files", []),
                    "filtered_out_count": task.task_metadata.get("filtered_out_count", 0),
                    "content_deduped_count": task.task_metadata.get("content_deduped_count", 0),
                    "content_deduped_files": task.task_metadata.get("content_deduped_files", []),
                    "renamed_collision_files": task.task_metadata.get("renamed_collision_files", []),
                    "progress_log": task.task_metadata.get("progress_log", []),
                    "awaiting_manual_match": task.task_metadata.get("awaiting_manual_match", False),
                    "manual_match_completed": task.task_metadata.get("manual_match_completed", False),
                    "manual_match_applied_pairs": task.task_metadata.get("manual_match_applied_pairs", 0),
                    "manual_match_deleted_subtitles": task.task_metadata.get("manual_match_deleted_subtitles", 0),
                    "naming_strategy": task.task_metadata.get("naming_strategy", "audio"),
                    "linked_subtitle_cleanup_result": task.task_metadata.get("linked_subtitle_cleanup_result"),
                }
                for task in rj_tasks
            ]
        }
    except Exception as e:
        logger.error(f"获取 RJ 字幕抓取状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/subtitle-import/pending")
async def list_pending_linked_subtitle_imports():
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        items = await service.list_pending_imports()
        return {
            "success": True,
            "items": items,
        }
    except Exception as e:
        logger.error(f"获取字幕补配预检列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取预检列表失败: {str(e)}")


@app.post("/api/subtitle-import/pending/{record_id}/execute")
async def execute_pending_linked_subtitle_import(record_id: str, request: LinkedSubtitlePendingImportExecuteRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_pending_import(
            record_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            activity_result = result if isinstance(result, dict) else {"success": True}
            activity_preview = activity_result.get("preview") if isinstance(activity_result.get("preview"), dict) else {}
            activity_archive_path = str(
                activity_result.get("source_path")
                or activity_preview.get("source_path")
                or ""
            ).strip()
            log_from_subtitle_import_result(
                "pending_execute",
                activity_result,
                archive_path=activity_archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 字幕补配预检执行记录失败", exc_info=True)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"执行字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行补配失败: {str(e)}")


@app.post("/api/subtitle-import/pending/clear")
async def clear_pending_linked_subtitle_imports(request: LinkedSubtitlePendingClearRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.clear_pending_imports(
            record_ids=request.record_ids,
            clear_all=request.clear_all,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"清除字幕补配预检单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除预检单失败: {str(e)}")


@app.post("/api/subtitle-import/archive/preview")
async def preview_linked_subtitle_archive_import(request: LinkedSubtitleArchivePreviewRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        preview = await service.preview_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/archive/import")
async def execute_linked_subtitle_archive_import(request: LinkedSubtitleArchiveImportRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_archive_import(
            request.archive_path,
            preferred_library_id=request.preferred_library_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "archive_import",
                result if isinstance(result, dict) else {},
                archive_path=request.archive_path,
            )
        except Exception:
            logger.debug("[操作记录] 压缩包补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"压缩包字幕补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/folder/preview")
async def preview_linked_subtitle_folder_import(request: LinkedSubtitleFolderPreviewRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        preview = await service.preview_subtitle_folder_import(
            request.folder_path,
            preferred_library_id=request.preferred_library_id,
            source_rjcode_hint=request.source_rjcode_hint,
        )
        return {"success": True, "preview": preview}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配预检失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预检失败: {str(e)}")


@app.post("/api/subtitle-import/folder/import")
async def execute_linked_subtitle_folder_import(request: LinkedSubtitleFolderImportRequest):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.execute_subtitle_folder_import(
            request.folder_path,
            preferred_library_id=request.preferred_library_id,
            target_library_id=request.target_library_id,
            target_folder_path=request.target_folder_path,
            source_rjcode_hint=request.source_rjcode_hint,
            use_filter_rules=request.use_filter_rules,
            subtitle_filter_rules=request.subtitle_filter_rules,
        )
        try:
            from ..core.activity_log_service import log_from_subtitle_import_result

            log_from_subtitle_import_result(
                "folder_import",
                result if isinstance(result, dict) else {},
                folder_path=request.folder_path,
            )
        except Exception:
            logger.debug("[操作记录] 文件夹补配记录失败", exc_info=True)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"字幕文件夹补配执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.post("/api/subtitle-import/task/{task_id}/cleanup")
async def cleanup_linked_subtitle_workbench(task_id: str):
    from ..core.linked_subtitle_import_service import get_linked_subtitle_import_service

    try:
        service = get_linked_subtitle_import_service()
        result = await service.cleanup_workbench_subtitles(task_id)
        return {"success": True, "result": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"瀛楀箷琛ラ厤宸ヤ綔鍙版枃鏈竻鐞嗗け璐? {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"娓呯悊澶辫触: {str(e)}")


@app.get("/api/rj-subtitle/connectivity-test")
async def rj_subtitle_connectivity_test():
    """测试 RJ 字幕流程依赖的远端连通性。"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        service = get_asmr_download_service()
        return await service.test_connectivity()
    except Exception as e:
        logger.error(f"RJ 字幕连通性测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"连通性测试失败: {str(e)}")


class ASMRSyncScanRequest(BaseModel):
    """ASMR 同步扫描请求"""
    folder_path: str

class ASMRSyncStartRequest(BaseModel):
    """ASMR 同步开始请求"""
    items: List[dict]  # [{rjcode, subtitle_folder, work_title}]
    auto_classify: bool = True


class ASMRSyncEnhancedPlanRequest(BaseModel):
    """增强下载计划请求"""
    rjcodes: List[str]
    folder_path: Optional[str] = ""
    resource_types: List[str] = []
    audio_formats: List[str] = []
    subtitle_languages: List[str] = []
    include_existing: bool = False


class ASMRSyncEnhancedStartRequest(BaseModel):
    """增强下载启动请求"""
    items: List[dict]  # [{rjcode, work_title, selected_resources, folder_path, upload_options}]
    auto_classify: bool = False


class ASMRSyncEnhancedPriorityRequest(BaseModel):
    queue_priority: int


class CircleCompletionIndexRequest(BaseModel):
    circle_query: str
    force_refresh: bool = False
    include_dlsite: bool = True
    include_kikoeru: bool = True
    only_new_works: bool = False


class CircleCompletionIndexJobRequest(BaseModel):
    circle_query: str
    circle_queries: List[str] = []
    force_refresh: bool = True
    include_dlsite: bool = True
    include_kikoeru: bool = True
    only_new_works: bool = False
    is_refresh_all: bool = False


class CircleCompletionDownloadPreviewRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]
    requested_rjcodes: Dict[str, List[str]] = {}


class CircleCompletionRefreshSelectedRequest(BaseModel):
    circle_id: str
    canonical_rjcodes: List[str]
    force_refresh: bool = False


class CircleCompletionRefreshSelectedJobRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    canonical_rjcodes: List[str]
    force_refresh: bool = False


class CircleCompletionDownloadStartRequest(BaseModel):
    circle_id: str
    circle_name: str = ""
    items: List[dict]
    batch_options: Dict[str, Any] = {}


class ASMRRetryFailedResourcesRequest(BaseModel):
    relative_paths: List[str] = []


class ASMRReimportDownloadedRequest(BaseModel):
    target_library_id: str
    target_subdir: str = ""


class ASMRReimportLocalDownloadRequest(BaseModel):
    download_root: str
    rjcode: str
    circle_name: str = ""
    target_library_id: str
    target_subdir: str = ""


class ASMRSyncLocateRJRequest(BaseModel):
    """跨库存按 RJ 号定位作品文件夹请求"""
    rjcodes: List[str]
    library_ids: Optional[List[str]] = None


_circle_completion_refresh_history: dict[str, deque[float]] = defaultdict(deque)


def _resolve_circle_completion_force_refresh(circle_id: str, requested_force_refresh: bool = False) -> tuple[bool, str]:
    if requested_force_refresh:
        return True, "manual"
    normalized_circle_id = str(circle_id or "").strip()
    if not normalized_circle_id:
        return False, ""
    now_ts = datetime.now().timestamp()
    history = _circle_completion_refresh_history[normalized_circle_id]
    while history and now_ts - history[0] > 60:
        history.popleft()
    history.append(now_ts)
    if len(history) >= 3:
        return True, "auto_threshold"
    return False, ""


class LocalUploadStartRequest(BaseModel):
    source_library_id: str
    source_base_path: str
    selected_paths: List[str]
    target_library_id: str
    target_subdir: str = ""
    circle_name: str = ""

@app.post("/api/asmr-sync/scan")
async def asmr_sync_scan(request: ASMRSyncScanRequest):
    """扫描指定文件夹，返回发现的 RJ 号和字幕文件列表"""
    from ..core.subtitle_sync_service import get_subtitle_sync_service

    try:
        folder_path = request.folder_path

        if not os.path.exists(folder_path):
            raise HTTPException(status_code=400, detail="指定的文件夹不存在")

        if not os.path.isdir(folder_path):
            raise HTTPException(status_code=400, detail="指定的路径不是文件夹")

        subtitle_service = get_subtitle_sync_service()
        results = subtitle_service.scan_subtitle_folders(folder_path)

        return {
            "success": True,
            "folder_path": folder_path,
            "total_found": len(results),
            "items": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫描字幕文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@app.post("/api/asmr-sync/preview")
async def asmr_sync_preview(request: Request):
    """预览下载任务（获取文件列表、预估下载量、搜索最佳版本）"""
    from ..core.asmr_download_service import get_asmr_download_service

    try:
        data = await request.json()
        rjcode = data.get("rjcode")

        if not rjcode:
            raise HTTPException(status_code=400, detail="RJ号不能为空")

        asmr_service = get_asmr_download_service()

        # 获取所有关联版本
        linked_works = await asmr_service.get_linked_works_from_dlsite(rjcode)
        available_versions = []

        for work in linked_works:
            work_info = await asmr_service.fetch_work_info(work.workno)
            tracks = await asmr_service.fetch_track_list(work.workno) if work_info else None

            available_versions.append({
                "rjcode": work.workno,
                "lang": work.lang,
                "priority": work.priority,
                "available": work_info is not None and tracks is not None and len(tracks) > 0,
                "title": work_info.get('title', '') if work_info else '',
                "file_count": len(tracks) if tracks else 0
            })

            # 添加延迟避免请求过快
            await asyncio.sleep(0.3)

        # 找到最佳可用版本
        actual_rjcode, work_info = await asmr_service.find_best_available_work(rjcode)

        if not work_info:
            return {
                "success": False,
                "rjcode": rjcode,
                "error": "在 asmr.one 上未找到该作品的任何版本",
                "tried_versions": [
                    {"rjcode": v["rjcode"], "lang": v["lang"]}
                    for v in available_versions
                ]
            }

        # 获取文件列表
        tracks = await asmr_service.fetch_track_list(actual_rjcode)
        if tracks is None:
            return {
                "success": False,
                "rjcode": rjcode,
                "actual_rjcode": actual_rjcode,
                "error": "无法获取文件列表"
            }

        # 扁平化文件列表
        all_files = asmr_service._flatten_tracks(tracks)

        # 应用筛选规则
        config = get_config()
        filter_rules = config.filter.rules
        filtered_files = asmr_service.filter_files(all_files, filter_rules) if filter_rules else all_files

        # 计算总大小
        total_size = sum(f.get('size', 0) for f in filtered_files)

        # 获取实际版本的语言
        actual_version = next((v for v in available_versions if v["rjcode"] == actual_rjcode), {})

        return {
            "success": True,
            "rjcode": rjcode,
            "actual_rjcode": actual_rjcode,
            "title": work_info.get('title', '未知标题'),
            "lang": actual_version.get("lang", "JPN"),
            "total_files": len(all_files),
            "filtered_files": len(filtered_files),
            "total_size": total_size,
            "available_versions": available_versions,
            "files": [
                {
                    "title": f.get('title'),
                    "size": f.get('size', 0),
                    "type": f.get('type')
                }
                for f in filtered_files[:50]  # 只返回前50个用于预览
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"预览下载任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预览失败: {str(e)}")


@app.post("/api/asmr-sync/start")
async def asmr_sync_start(request: ASMRSyncStartRequest):
    """开始同步下载任务"""
    from ..core.task_engine import Task, TaskType, get_task_engine

    try:
        items = request.items
        auto_classify = request.auto_classify

        if not items:
            raise HTTPException(status_code=400, detail="没有要下载的作品")

        engine = get_task_engine()
        created_tasks = []

        for item in items:
            rjcode = item.get("rjcode")
            subtitle_folder = item.get("subtitle_folder")
            work_title = item.get("work_title", "")

            if not rjcode or not subtitle_folder:
                continue

            # 创建任务
            task = Task(
                task_type=TaskType.ASMR_SYNC_DOWNLOAD,
                source_path=subtitle_folder,
                auto_classify=auto_classify,
                metadata={
                    "rjcode": rjcode,
                    "subtitle_folder": subtitle_folder,
                    "work_title": work_title,
                    "download_mode": "legacy",
                }
            )

            await engine.submit(task)
            created_tasks.append({
                "task_id": task.id,
                "rjcode": rjcode,
                "work_title": work_title
            })

        return {
            "success": True,
            "message": f"已创建 {len(created_tasks)} 个下载任务",
            "tasks": created_tasks
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"开始同步下载失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@app.post("/api/asmr-sync/enhanced/plan")
async def asmr_sync_enhanced_plan(request: ASMRSyncEnhancedPlanRequest):
    """为输入的 RJ 号构建增强下载计划。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    if not request.rjcodes:
        raise HTTPException(status_code=400, detail="至少需要一个 RJ 号")

    service = get_asmr_resource_service()
    plans = []
    errors = []
    filters = {
        "resource_types": request.resource_types,
        "audio_formats": request.audio_formats,
        "subtitle_languages": request.subtitle_languages,
        "include_existing": request.include_existing,
    }

    for raw_rjcode in request.rjcodes:
        normalized_rjcode = service.normalize_rjcode(raw_rjcode)
        if not normalized_rjcode:
            continue
        try:
            plan = await service.build_download_plan(
                rjcode=normalized_rjcode,
                folder_path=str(request.folder_path or "").strip(),
                filters=filters,
                refresh=True,
            )
            plans.append(plan)
        except Exception as exc:
            logger.warning("构建增强下载计划失败: %s (%s)", normalized_rjcode, exc)
            errors.append({
                "rjcode": normalized_rjcode,
                "error": str(exc),
            })

    return {
        "success": len(plans) > 0,
        "plans": plans,
        "errors": errors,
        "requested_count": len(request.rjcodes),
        "planned_count": len(plans),
    }


@app.post("/api/asmr-sync/enhanced/start")
async def asmr_sync_enhanced_start(request: ASMRSyncEnhancedStartRequest):
    """启动增强下载任务，支持按文件清单下载。"""
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    config = get_config()

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可启动的增强下载任务")

    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    service = get_asmr_resource_service()
    created_tasks = []
    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode:
            continue
        if not session_id:
            raise HTTPException(status_code=400, detail=f"{rjcode} 缺少 session_id")
        if not selected_resources:
            raise HTTPException(status_code=400, detail=f"{rjcode} 没有选中任何资源")

        raw_postprocess_options = dict(item.get("postprocess_options") or {})
        raw_download_base_path = str(item.get("download_base_path") or "").strip()
        task_metadata = {
            "rjcode": rjcode,
            "work_title": str(item.get("work_title") or ""),
            "cover_url": str(item.get("cover_url") or item.get("image_url") or item.get("mainCoverUrl") or ""),
            "folder_path": str(item.get("folder_path") or ""),
            "download_mode": "enhanced",
            "session_id": session_id,
            "selected_resources": selected_resources,
            "selected_resource_count": len(selected_resources),
            "upload_options": dict(item.get("upload_options") or {}),
            "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
            "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
            "priority": int(item.get("queue_priority") or item.get("priority") or 100),
            "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
            "verify_summary": {},
            "upload_summary": {},
            "retry_summary": {},
            "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
            "source_page": "asmr-sync",
            "source_action": "enhanced_download",
            "source_label": str(item.get("work_title") or rjcode),
        }
        if raw_postprocess_options:
            task_metadata["postprocess_options"] = raw_postprocess_options
        if raw_download_base_path:
            task_metadata["download_base_path"] = raw_download_base_path
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=bool(request.auto_classify),
            metadata=task_metadata,
        )
        await engine.submit(task)
        service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })

    return {
        "success": len(created_tasks) > 0,
        "message": f"已创建 {len(created_tasks)} 个增强下载任务",
        "tasks": created_tasks,
    }


_LOCATE_RJ_CONCURRENCY = 4
_locate_rj_semaphore: Optional[asyncio.Semaphore] = None


def _get_locate_rj_semaphore() -> asyncio.Semaphore:
    global _locate_rj_semaphore
    if _locate_rj_semaphore is None:
        _locate_rj_semaphore = asyncio.Semaphore(_LOCATE_RJ_CONCURRENCY)
    return _locate_rj_semaphore


@app.post("/api/asmr-sync/enhanced/locate-rj")
async def asmr_sync_enhanced_locate_rj(request: ASMRSyncLocateRJRequest):
    """跨库存按 RJ 号定位作品文件夹（用于"直放已有路径"模式）。

    多个 RJ 用 asyncio.gather 并发，但加全局信号量限流，避免对群晖 / NAS
    打出过多并发请求；本地搜索靠 LibraryManager 内部的结果 TTL 缓存复用。
    """
    from ..core.library_manager import get_library_manager

    manager = get_library_manager()
    rjcodes_norm: list[str] = []
    seen: set[str] = set()
    for raw in request.rjcodes or []:
        normalized = str(raw or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rjcodes_norm.append(normalized)
    if not rjcodes_norm:
        return {"success": True, "results": []}

    library_ids = list(request.library_ids) if request.library_ids else None
    semaphore = _get_locate_rj_semaphore()

    async def _locate_one(rj: str) -> dict[str, Any]:
        async with semaphore:
            try:
                matches = await manager.find_rj_in_libraries(rj, library_ids=library_ids)
            except Exception as exc:
                logger.warning("locate-rj 失败: rj=%s err=%s", rj, exc, exc_info=True)
                matches = []
            return {"rjcode": rj, "matches": matches}

    results = await asyncio.gather(*[_locate_one(rj) for rj in rjcodes_norm])
    return {"success": True, "results": list(results)}


@app.get("/api/asmr-sync/enhanced/dashboard")
async def asmr_sync_enhanced_dashboard():
    """增强下载监控看板摘要。"""
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "dashboard": get_asmr_resource_service().get_dashboard_summary(),
        }
    except Exception as exc:
        logger.error("获取增强下载看板失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取监控看板失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions")
async def asmr_sync_enhanced_sessions(limit: int = 50):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "sessions": get_asmr_resource_service().list_sessions(limit=limit),
        }
    except Exception as exc:
        logger.error("获取增强下载会话列表失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(exc)}")


@app.get("/api/asmr-sync/enhanced/sessions/{session_id}")
async def asmr_sync_enhanced_session_detail(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": get_asmr_resource_service().get_session_detail(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("获取增强下载会话详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/priority")
async def asmr_sync_enhanced_session_priority(session_id: str, request: ASMRSyncEnhancedPriorityRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().update_session_priority(session_id, request.queue_priority),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("调整增强下载会话优先级失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"调整优先级失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/pause")
async def asmr_sync_enhanced_session_pause(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "pause"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("暂停增强下载会话失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"暂停会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/resume")
async def asmr_sync_enhanced_session_resume(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().control_session(session_id, "resume"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("恢复增强下载会话失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/cancel", summary="取消增强下载会话")
async def asmr_sync_enhanced_session_cancel(session_id: str, request: Request):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        cleanup = bool(body.get("cleanup", True))
        service = get_asmr_resource_service()
        if cleanup:
            session = await service.cancel_session_with_cleanup(session_id)
        else:
            session = await service.control_session(session_id, "cancel")
        return {"success": True, "session": session}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("取消增强下载会话失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消会话失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-failed")
async def asmr_sync_enhanced_session_retry_failed(session_id: str):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session(session_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话失败资源失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败资源失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/retry-files")
async def asmr_sync_enhanced_session_retry_files(session_id: str, request: ASMRRetryFailedResourcesRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().retry_failed_session_resources(session_id, request.relative_paths),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("重试增强下载会话指定失败文件失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试指定失败文件失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/sessions/{session_id}/reimport-downloaded")
async def asmr_sync_enhanced_session_reimport_downloaded(session_id: str, request: ASMRReimportDownloadedRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "session": await get_asmr_resource_service().reimport_downloaded_session(
                session_id,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("从本地已下载内容重新入库失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新入库失败: {str(exc)}")


@app.post("/api/asmr-sync/enhanced/reimport-local-download")
async def asmr_sync_enhanced_reimport_local_download(request: ASMRReimportLocalDownloadRequest):
    from ..core.asmr_resource_service import get_asmr_resource_service

    try:
        return {
            "success": True,
            "result": await get_asmr_resource_service().reimport_local_download_root(
                download_root=request.download_root,
                rjcode=request.rjcode,
                target_library_id=request.target_library_id,
                target_subdir=request.target_subdir,
                circle_name=request.circle_name,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("从本地下载目录直接入库失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"从本地下载目录直接入库失败: {str(exc)}")


@app.post("/api/circle-completion/index")
async def circle_completion_index(request: CircleCompletionIndexRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().index_circle_catalog(
            request.circle_query,
            force_refresh=bool(request.force_refresh),
            include_dlsite=bool(request.include_dlsite),
            include_kikoeru=bool(request.include_kikoeru),
            only_new_works=bool(request.only_new_works),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"建立社团索引失败: {str(exc)}")


@app.post("/api/circle-completion/index/start")
async def circle_completion_index_start(request: CircleCompletionIndexJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_queries = []
        for value in list(request.circle_queries or []):
            query = str(value or "").strip()
            if query and query not in circle_queries:
                circle_queries.append(query)
        single_circle_query = str(request.circle_query or "").strip()
        if single_circle_query and single_circle_query not in circle_queries:
            circle_queries.append(single_circle_query)
        if not circle_queries:
            raise ValueError("社团名不能为空")
        circle_query = circle_queries[0]
        is_batch = len(circle_queries) > 1
        is_refresh_all = bool(request.is_refresh_all) and is_batch
        if is_refresh_all:
            source_label = f"全部刷新 {len(circle_queries)} 个社团"
            source_action_kind = "refresh_all_circles"
        elif is_batch:
            source_label = f"批量补全 {len(circle_queries)} 个社团"
            source_action_kind = "index_start"
        else:
            source_label = circle_query
            source_action_kind = "index_start"
        business_key = circle_query if not is_batch else f"batch:{'|'.join(circle_queries[:20])}"

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_INDEX,
            source_path=source_label,
            auto_classify=False,
            metadata={
                "circle_query": circle_query,
                "circle_queries": circle_queries,
                "circle_name": circle_query,
                "force_refresh": bool(request.force_refresh),
                "include_dlsite": bool(request.include_dlsite),
                "include_kikoeru": bool(request.include_kikoeru),
                "only_new_works": bool(request.only_new_works),
                "is_batch": is_batch,
                "batch_total": len(circle_queries),
                "is_refresh_all": is_refresh_all,
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": source_action_kind,
                "source_label": source_label,
                "business_key": business_key,
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": source_action_kind,
            "source_label": source_label,
            "business_key": business_key,
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": circle_query,
            "circle_id": "",
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {
                "only_new_works": bool(request.only_new_works),
                "is_batch": is_batch,
                "batch_total": len(circle_queries),
                "completed_queries": 0,
                "failed_queries": 0,
                "current_circle_query": circle_query,
            },
            "result": {},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动社团索引任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动社团索引任务失败: {str(exc)}")


@app.get("/api/circle-completion/index/jobs/{job_id}")
async def circle_completion_index_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("索引任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_query": str(metadata.get("current_circle_query") or metadata.get("circle_query") or task.source_path or "").strip(),
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": {
                **dict(metadata.get("index_meta") or {}),
                "only_new_works": bool(metadata.get("only_new_works")),
                "is_batch": bool(metadata.get("is_batch")),
                "is_refresh_all": bool(metadata.get("is_refresh_all")),
                "batch_total": int(metadata.get("batch_total") or 0),
            },
            "result": {
                **dict(metadata.get("index_result") or {}),
                "batch_results": list(metadata.get("index_batch_results") or []),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团索引任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团索引任务失败: {str(exc)}")


@app.get("/api/circle-completion/circles")
async def circle_completion_circles(keyword: str = "", limit: int = 30):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().search_circles(keyword, limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/recent")
async def circle_completion_recent(limit: int = 20):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().list_recent_indexes(limit=limit)
        return {"success": True, "circles": circles}
    except Exception as exc:
        logger.error("查询最近社团索引失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询最近社团索引失败: {str(exc)}")


@app.get("/api/circle-completion/circles/names")
async def circle_completion_all_circle_names():
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        circles = await get_circle_completion_service().search_circles("", limit=9999)
        names = [c["circle_name"] for c in circles if c.get("circle_name")]
        return {"success": True, "names": names, "total": len(names)}
    except Exception as exc:
        logger.error("获取所有社团名失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取所有社团名失败: {str(exc)}")


@app.get("/api/circle-completion/circles/{circle_id}")
async def circle_completion_detail(
    circle_id: str,
    only_missing: bool = False,
    only_downloadable: bool = False,
    include_dl_only: bool = True,
):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().build_circle_completion_view(
            circle_id,
            only_missing=bool(only_missing),
            only_downloadable=bool(only_downloadable),
            include_dl_only=bool(include_dl_only),
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询社团补全详情失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询社团补全详情失败: {str(exc)}")


@app.post("/api/circle-completion/download/preview")
async def circle_completion_download_preview(request: CircleCompletionDownloadPreviewRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        result = await get_circle_completion_service().preview_batch_download(
            request.circle_id,
            request.canonical_rjcodes,
            request.requested_rjcodes,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("预览社团批量下载失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"预览批量下载失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected")
async def circle_completion_refresh_selected(request: CircleCompletionRefreshSelectedRequest):
    from ..core.circle_completion_service import get_circle_completion_service

    try:
        force_refresh, force_refresh_reason = _resolve_circle_completion_force_refresh(
            request.circle_id,
            bool(request.force_refresh),
        )
        result = await get_circle_completion_service().refresh_circle_works(
            request.circle_id,
            request.canonical_rjcodes,
            force_refresh=force_refresh,
        )
        return {
            "success": True,
            **result,
            "meta": {
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("批量刷新社团作品状态失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"批量刷新社团作品状态失败: {str(exc)}")


@app.post("/api/circle-completion/refresh-selected/start")
async def circle_completion_refresh_selected_start(request: CircleCompletionRefreshSelectedJobRequest):
    from ..core.task_engine import Task, TaskType, TaskStatus, get_task_engine

    try:
        circle_id = str(request.circle_id or "").strip()
        circle_name = str(request.circle_name or "").strip()
        canonical_rjcodes = [str(code or "").strip() for code in list(request.canonical_rjcodes or []) if str(code or "").strip()]
        if not circle_id:
            raise ValueError("缺少社团标识")
        if not canonical_rjcodes:
            raise ValueError("没有选中要刷新的作品")
        force_refresh, force_refresh_reason = _resolve_circle_completion_force_refresh(
            circle_id,
            bool(request.force_refresh),
        )

        task = Task(
            task_type=TaskType.CIRCLE_COMPLETION_REFRESH_SELECTED,
            source_path=circle_name or circle_id,
            auto_classify=False,
            metadata={
                "circle_id": circle_id,
                "circle_name": circle_name,
                "canonical_rjcodes": canonical_rjcodes,
                "selected_count": len(canonical_rjcodes),
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "refresh_selected",
                "source_label": circle_name or circle_id,
                "business_key": f"{circle_id}:refresh_selected",
                "progress_log": [],
            },
        )
        task.ensure_business_context("circle_completion", {
            "source_page": "circle-completion",
            "source_action": "refresh_selected",
            "source_label": circle_name or circle_id,
            "business_key": f"{circle_id}:refresh_selected",
        })
        await get_task_engine().submit(task)
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": circle_id,
            "circle_name": circle_name,
            "selected_count": len(canonical_rjcodes),
            "started_at": task.created_at.isoformat() if task.created_at else None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "error_message": None,
            "meta": {
                "force_refresh": bool(force_refresh),
                "force_refresh_reason": force_refresh_reason,
            },
            "result": {},
            "progress_log": [],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("启动批量刷新社团作品任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动批量刷新社团作品任务失败: {str(exc)}")


@app.get("/api/circle-completion/refresh-selected/jobs/{job_id}")
async def circle_completion_refresh_selected_job_status(job_id: str):
    from ..core.task_engine import get_task_engine

    try:
        task = get_task_engine().get_task(job_id)
        if task is None:
            raise ValueError("刷新任务不存在")
        metadata = dict(task.task_metadata or {})
        started_at = task.started_at or task.created_at
        finished_at = task.completed_at
        elapsed_seconds = 0.0
        if started_at:
            end_time = finished_at or datetime.now()
            elapsed_seconds = max(0.0, (end_time - started_at).total_seconds())
        return {
            "success": True,
            "job_id": task.id,
            "status": task.status.value,
            "progress": int(task.progress or 0),
            "current_step": task.current_step,
            "circle_id": str(metadata.get("circle_id") or "").strip(),
            "circle_name": str(metadata.get("circle_name") or task.source_path or "").strip(),
            "selected_count": int(metadata.get("selected_count") or 0),
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error_message": task.error_message,
            "meta": {
                **dict(metadata.get("refresh_meta") or {}),
                "force_refresh": bool(metadata.get("force_refresh")),
                "force_refresh_reason": str(metadata.get("force_refresh_reason") or ""),
            },
            "result": dict(metadata.get("refresh_result") or {}),
            "progress_log": list(metadata.get("progress_log") or []),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("查询批量刷新社团作品任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询批量刷新社团作品任务失败: {str(exc)}")


@app.post("/api/circle-completion/download/start")
async def circle_completion_download_start(request: CircleCompletionDownloadStartRequest):
    from ..core.activity_log_service import log_circle_completion_event
    from ..core.asmr_resource_service import get_asmr_resource_service
    from ..core.task_engine import Task, TaskType, get_task_engine

    if not request.items:
        raise HTTPException(status_code=400, detail="没有可创建的下载项")

    config = get_config()
    batch_id = str(uuid.uuid4())
    engine = get_task_engine()
    engine.set_max_concurrent(int(getattr(config.asmr_sync, "enhanced_max_parallel_sessions", 5) or 5))
    session_service = get_asmr_resource_service()
    created_tasks = []
    child_rows = []
    batch_options = dict(request.batch_options or {})
    download_base_path = str(batch_options.get("download_base_path") or "").strip()
    target_library_id = str(batch_options.get("target_library_id") or "").strip()
    target_subdir = str(batch_options.get("target_subdir") or "").strip()
    naming_mode = str(batch_options.get("naming_mode") or "api").strip().lower() or "api"
    classify_mode = str(batch_options.get("classify_mode") or "circle").strip().lower() or "circle"

    for item in request.items:
        rjcode = str(item.get("rjcode") or "").strip().upper()
        session_id = str(item.get("session_id") or "").strip()
        selected_resources = list(item.get("selected_resources") or [])
        if not rjcode or not session_id or not selected_resources:
            continue
        task = Task(
            task_type=TaskType.ASMR_SYNC_DOWNLOAD,
            source_path=str(item.get("folder_path") or rjcode),
            auto_classify=False,
            metadata={
                "rjcode": rjcode,
                "work_title": str(item.get("work_title") or rjcode),
                "cover_url": str(item.get("cover_url") or item.get("image_url") or item.get("mainCoverUrl") or ""),
                "folder_path": str(item.get("folder_path") or ""),
                "download_mode": "enhanced",
                "session_id": session_id,
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
                "circle_name": request.circle_name,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "selected_resources": selected_resources,
                "selected_resource_count": len(selected_resources),
                "upload_options": dict(item.get("upload_options") or {}),
                "download_base_path": download_base_path,
                "postprocess_options": {
                    "enabled": True,
                    "target_library_id": target_library_id,
                    "target_subdir": target_subdir,
                    "naming_mode": naming_mode,
                    "classify_mode": classify_mode,
                    "circle_name": str((item.get("postprocess_options") or {}).get("circle_name") or request.circle_name or ""),
                },
                "verify_md5_after_download": bool(item.get("verify_md5_after_download", True)),
                "download_timeout_seconds": int(item.get("download_timeout_seconds") or 0),
                "priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "queue_priority": int(item.get("queue_priority") or item.get("priority") or 100),
                "resource_filter_snapshot": dict(item.get("resource_filter_snapshot") or {}),
                "task_domain": "circle_completion",
                "source_page": "circle-completion",
                "source_action": "batch_download",
                "source_label": str(item.get("work_title") or rjcode),
                "business_key": str(item.get("canonical_rjcode") or rjcode),
            },
            rjcode=rjcode,
        )
        await engine.submit(task)
        session_service._update_session(
            session_id,
            task_id=task.id,
            status="queued",
            queue_priority=int(item.get("queue_priority") or item.get("priority") or 100),
            target_path=str((item.get("upload_options") or {}).get("target_path") or ""),
            upload_mode=str((item.get("upload_options") or {}).get("mode") or "disabled"),
            statistics={
                "selected_resource_count": len(selected_resources),
                "upload_library_id": str((item.get("upload_options") or {}).get("library_id") or ""),
                "parent_session_id": batch_id,
                "circle_id": request.circle_id,
                "target_library_id": target_library_id,
                "target_subdir": target_subdir,
                "naming_mode": naming_mode,
                "classify_mode": classify_mode,
                "circle_name": str((item.get("postprocess_options") or {}).get("circle_name") or request.circle_name or ""),
            },
            selected_resources=selected_resources,
        )
        created_tasks.append({
            "task_id": task.id,
            "session_id": session_id,
            "rjcode": rjcode,
            "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
            "work_title": str(item.get("work_title") or ""),
            "selected_resource_count": len(selected_resources),
        })
        child_rows.append({
            "id": task.id,
            "category": "circle_completion",
            "category_label": "社团补全",
            "action": "download_item_queued",
            "status": "success",
            "summary": f"{rjcode} 已加入下载队列，共 {len(selected_resources)} 个资源",
            "detail": {
                "session_id": session_id,
                "parent_session_id": batch_id,
                "canonical_rjcode": str(item.get("canonical_rjcode") or rjcode),
                "display_rjcodes": list(item.get("display_rjcodes") or [rjcode]),
                "downloadable": True,
                "selected_resource_count": len(selected_resources),
                "download_base_path": download_base_path or None,
                "target_library_id": target_library_id or None,
                "target_subdir": target_subdir or None,
                "naming_mode": naming_mode,
                "classify_mode": classify_mode,
            },
            "task_id": task.id,
            "rjcode": rjcode,
            "created_at": datetime.now().isoformat(),
        })

    if not created_tasks:
        raise HTTPException(status_code=400, detail="没有有效下载项")

    log_circle_completion_event(
        "download_batch_start",
        summary=f"{request.circle_name or request.circle_id} 已创建 {len(created_tasks)} 个下载子任务",
        circle_id=request.circle_id,
        circle_name=request.circle_name or request.circle_id,
        batch_id=batch_id,
        detail={
            "items": created_tasks,
            "child_rows": child_rows,
            "download_base_path": download_base_path or None,
            "target_library_id": target_library_id or None,
            "target_subdir": target_subdir or None,
            "naming_mode": naming_mode,
            "classify_mode": classify_mode,
        },
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "circle_id": request.circle_id,
        "tasks": created_tasks,
        "message": f"已创建 {len(created_tasks)} 个社团补全下载任务",
    }

@app.post("/api/local-upload/start")
async def local_upload_start(request: LocalUploadStartRequest):
    from pathlib import PurePosixPath
    from ..core.library_manager import get_library_manager
    from ..core.task_engine import Task, TaskType, get_task_engine
    try:
        source_library_id = str(request.source_library_id or "").strip()
        source_base_path = str(request.source_base_path or "").strip()
        selected_paths = [str(p or "").strip() for p in (request.selected_paths or []) if str(p or "").strip()]
        target_library_id = str(request.target_library_id or "").strip()
        target_subdir = str(request.target_subdir or "").strip()
        circle_name = str(request.circle_name or "").strip()
        if not source_base_path:
            raise HTTPException(status_code=400, detail="缺少来源目录")
        if not selected_paths:
            raise HTTPException(status_code=400, detail="没有选中要上传的目录")
        if not target_library_id:
            raise HTTPException(status_code=400, detail="缺少目标库存")
        if source_library_id:
            manager = get_library_manager()
        else:
            manager = get_library_manager()
            source_base_real = os.path.abspath(source_base_path)
            if not os.path.isdir(source_base_real):
                raise HTTPException(status_code=400, detail="来源目录不存在")
            invalid_paths = [
                path for path in selected_paths
                if not os.path.isdir(path) or os.path.commonpath([source_base_real, os.path.abspath(path)]) != source_base_real
            ]
            if invalid_paths:
                raise HTTPException(status_code=400, detail="选中的来源目录无效或不在来源根目录内")

        target_library = manager.get_library_definition(target_library_id)
        target_root = PurePosixPath(str(target_library.root_path or "").replace("\\", "/"))
        normalized_target_subdir = target_subdir.strip("/\\")
        target_root_text = str(target_root).replace("\\", "/").rstrip("/")
        target_root_name = PurePosixPath(target_root_text or "/").name
        if normalized_target_subdir in {target_root_name, target_root_text.lstrip("/")}:
            normalized_target_subdir = ""
        if normalized_target_subdir:
            target_root = target_root / normalized_target_subdir
        if circle_name:
            target_root = target_root / circle_name
        selected_items = []
        for selected_path in selected_paths:
            relative_target_dir = str(target_root).replace("\\", "/").strip("/")
            selected_items.append({
                "source_path": selected_path,
                "relative_target_dir": relative_target_dir,
            })

        preview_target_path = str(target_root)
        if len(selected_paths) == 1:
            preview_target_path = str(PurePosixPath(preview_target_path) / os.path.basename(os.path.abspath(selected_paths[0])))

        task = Task(
            task_type=TaskType.LOCAL_LIBRARY_UPLOAD,
            source_path=source_base_path,
            metadata={
                "source_library_id": source_library_id,
                "source_base_path": source_base_path,
                "selected_paths": selected_paths,
                "selected_items": selected_items,
                "target_library_id": target_library_id,
                "target_subdir": normalized_target_subdir,
                "circle_name": circle_name,
                "target_path": preview_target_path.replace("\\", "/"),
                "selected_dir_count": len(selected_paths),
                "source_page": "circle_completion" if not source_library_id else "library",
                "source_action": "direct_reimport_upload" if not source_library_id else "upload_to_server",
                "source_label": circle_name or os.path.basename(source_base_path.rstrip("\\/")) or "上传到服务器",
            },
        )
        task.task_metadata["upload_files"] = []
        task.task_metadata["uploaded_files"] = []
        task.task_metadata["progress_log"] = []
        task.task_metadata["upload_runtime"] = {}
        task.ensure_business_context(
            "upload",
            defaults={
                "source_page": "library",
                "source_page": "circle_completion" if not source_library_id else "library",
                "source_action": "direct_reimport_upload" if not source_library_id else "upload_to_server",
                "source_label": circle_name or os.path.basename(source_base_path.rstrip("\\/")) or "上传到服务器",
                "business_key": f"{target_library_id}:{'|'.join(selected_paths)}",
            },
        )

        engine = get_task_engine()
        task_id = await engine.submit(task)
        return {
            "success": True,
            "task_id": task_id,
            "count": len(selected_paths),
            "message": f"已创建 {len(selected_paths)} 个目录上传任务",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("本地库存上传到群晖失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(exc)}")


@app.get("/api/local-upload/status")
async def local_upload_status(task_ids: str = "", include_hidden: bool = True):
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        requested_ids = [
            str(item or "").strip()
            for item in str(task_ids or "").split(",")
            if str(item or "").strip()
        ]
        all_tasks = engine.get_all_tasks(include_hidden=bool(include_hidden))
        upload_tasks = [t for t in all_tasks if t.type == TaskType.LOCAL_LIBRARY_UPLOAD]
        upload_task_map = {str(t.id): t for t in upload_tasks}
        if requested_ids:
            selected_tasks = [upload_task_map[task_id] for task_id in requested_ids if task_id in upload_task_map]
            seen_ids = {str(task.id) for task in selected_tasks}
            selected_tasks.extend([t for t in upload_tasks if str(t.id) not in seen_ids][:20])
            upload_tasks = selected_tasks

        return {
            "total_tasks": len(upload_tasks),
            "processing": len([t for t in upload_tasks if t.status.value == "processing"]),
            "pending": len([t for t in upload_tasks if t.status.value == "pending"]),
            "completed": len([t for t in upload_tasks if t.status.value == "completed"]),
            "failed": len([t for t in upload_tasks if t.status.value == "failed"]),
            "tasks": [
                {
                    "id": t.id,
                    "status": t.status.value,
                    "display_status": t.status.value,
                    "progress": t.progress,
                    "current_step": t.current_step,
                    "error_message": t.error_message,
                    "created_at": t.created_at.isoformat() if getattr(t, "created_at", None) else None,
                    "started_at": t.started_at.isoformat() if getattr(t, "started_at", None) else None,
                    "completed_at": t.completed_at.isoformat() if getattr(t, "completed_at", None) else None,
                    "source_path": t.source_path,
                    "output_path": getattr(t, "output_path", ""),
                    "upload_files": t.task_metadata.get("upload_files", []),
                    "uploaded_files": t.task_metadata.get("uploaded_files", []),
                    "upload_runtime": t.task_metadata.get("upload_runtime", {}),
                    "progress_log": t.task_metadata.get("progress_log", []),
                    "task_metadata": {
                        "source_library_id": t.task_metadata.get("source_library_id", ""),
                        "source_base_path": t.task_metadata.get("source_base_path", ""),
                        "selected_paths": t.task_metadata.get("selected_paths", []),
                        "selected_items": t.task_metadata.get("selected_items", []),
                        "selected_dir_count": t.task_metadata.get("selected_dir_count", 0),
                        "target_library_id": t.task_metadata.get("target_library_id", ""),
                        "target_subdir": t.task_metadata.get("target_subdir", ""),
                        "circle_name": t.task_metadata.get("circle_name", ""),
                        "target_path": t.task_metadata.get("target_path", ""),
                        "final_output_path": t.task_metadata.get("final_output_path", ""),
                        "upload_result": t.task_metadata.get("upload_result", {}),
                        "source_action": t.task_metadata.get("source_action", ""),
                        "source_label": t.task_metadata.get("source_label", ""),
                    },
                }
                for t in upload_tasks
            ],
        }
    except Exception as exc:
        logger.error("获取本地上传任务状态失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取上传状态失败: {str(exc)}")


@app.get("/api/asmr-sync/status")
async def asmr_sync_status():
    """获取当前同步任务状态"""
    from ..core.task_engine import TaskType, get_task_engine

    try:
        engine = get_task_engine()
        all_tasks = engine.get_all_tasks()

        # 过滤出 ASMR 同步任务
        asmr_tasks = [t for t in all_tasks if t.type == TaskType.ASMR_SYNC_DOWNLOAD]
        session_ids = {
            str(t.task_metadata.get("session_id") or "").strip()
            for t in asmr_tasks
            if str(t.task_metadata.get("session_id") or "").strip()
        }
        session_map = {}
        if session_ids:
            db = SessionLocal()
            try:
                rows = db.query(ASMRDownloadSession).filter(ASMRDownloadSession.id.in_(list(session_ids))).all()
                stale_rows_corrected = False
                for row in rows:
                    session = row.to_dict()
                    statistics = dict(session.get("statistics") or {})
                    local_root = str(session.get("local_download_root") or statistics.get("download_root") or "").strip()
                    local_count = int(session.get("local_downloaded_count") or 0)
                    local_ready = bool(session.get("local_download_ready"))
                    if local_root and os.path.isdir(local_root):
                        if local_count <= 0:
                            local_count = sum(
                                1
                                for item in (session.get("selected_resources") or [])
                                if os.path.exists(
                                    os.path.join(
                                        local_root,
                                        str(item.get("relative_path") or item.get("file_name") or "").strip().replace("/", os.sep),
                                    )
                                )
                            )
                        local_ready = local_ready or local_count > 0
                    else:
                        if local_ready or local_count > 0 or str(row.local_download_root or "").strip():
                            row.local_download_ready = False
                            row.local_download_root = None
                            row.local_downloaded_count = 0
                            stale_rows_corrected = True
                        local_root = ""
                        local_count = 0
                        local_ready = False
                    session_map[str(row.id)] = {
                        "local_download_ready": local_ready,
                        "local_download_root": local_root,
                        "local_downloaded_count": local_count,
                    }
                if stale_rows_corrected:
                    db.commit()
            finally:
                db.close()

        return {
            "total_tasks": len(asmr_tasks),
            "processing": len([t for t in asmr_tasks if t.status.value == "processing"]),
            "pending": len([t for t in asmr_tasks if t.status.value == "pending"]),
            "completed": len([t for t in asmr_tasks if t.status.value == "completed"]),
            "failed": len([t for t in asmr_tasks if t.status.value == "failed"]),
            "waiting_retry": len([t for t in asmr_tasks if t.status.value == "waiting_retry"]),
            "tasks": [
                {
                    "session_state": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}),
                    "id": t.id,
                    "rjcode": t.task_metadata.get("rjcode", ""),
                    "actual_rjcode": t.task_metadata.get("actual_rjcode", ""),
                    "work_title": t.task_metadata.get("work_title", ""),
                    "source_label": t.task_metadata.get("source_label", ""),
                    "status": t.status.value,
                    "display_status": "partial_failed" if (t.status.value == "completed" and (t.task_metadata.get("failed_files") or t.task_metadata.get("verification_failures") or t.task_metadata.get("failure_reason"))) else t.status.value,
                    "progress": t.progress,
                    "current_step": t.current_step,
                    "error_message": t.error_message,
                    "created_at": t.created_at.isoformat() if getattr(t, "created_at", None) else None,
                    "started_at": t.started_at.isoformat() if getattr(t, "started_at", None) else None,
                    "completed_at": t.completed_at.isoformat() if getattr(t, "completed_at", None) else None,
                    "output_path": getattr(t, "output_path", ""),
                    "download_files": t.task_metadata.get("download_files", []),
                    "download_runtime": t.task_metadata.get("download_runtime", {}),
                    "upload_files": t.task_metadata.get("upload_files", []),
                    "upload_runtime": t.task_metadata.get("upload_runtime", {}),
                    "failed_files": t.task_metadata.get("failed_files", []),
                    "uploaded_files": t.task_metadata.get("uploaded_files", []),
                    "verification_failures": t.task_metadata.get("verification_failures", []),
                    "progress_log": t.task_metadata.get("progress_log", []),
                    "performance_metrics": t.task_metadata.get("performance_metrics", {}),
                    "sync_result": t.task_metadata.get("sync_result", {}),
                    "subtitle_moved_to": t.task_metadata.get("subtitle_moved_to", ""),
                    "download_mode": t.task_metadata.get("download_mode", "legacy"),
                    "session_id": t.task_metadata.get("session_id", ""),
                    "queue_priority": t.task_metadata.get("queue_priority", t.task_metadata.get("priority", 100)),
                    "task_metadata": {
                        "retry_reason": t.task_metadata.get("retry_reason", ""),
                        "retry_count": t.task_metadata.get("retry_count", 0),
                        "retry_after": t.task_metadata.get("retry_after", ""),
                        "selected_resource_count": t.task_metadata.get("selected_resource_count", 0),
                        "selected_resources": t.task_metadata.get("selected_resources", []),
                        "verify_summary": t.task_metadata.get("verify_summary", {}),
                        "upload_summary": t.task_metadata.get("upload_summary", {}),
                        "retry_summary": t.task_metadata.get("retry_summary", {}),
                        "source_action": t.task_metadata.get("source_action", ""),
                        "circle_name": t.task_metadata.get("circle_name", ""),
                        "download_root": (
                            session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_root")
                            or t.task_metadata.get("download_root", "")
                        ),
                        "download_base_path": t.task_metadata.get("download_base_path", ""),
                        "final_output_path": t.task_metadata.get("final_output_path", ""),
                        "target_path": t.task_metadata.get("target_path", ""),
                        "failure_reason": t.task_metadata.get("failure_reason", ""),
                        "local_download_ready": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_ready", False),
                        "local_download_root": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_download_root", ""),
                        "local_downloaded_count": session_map.get(str(t.task_metadata.get("session_id") or "").strip(), {}).get("local_downloaded_count", 0),
                    }
                }
                for t in asmr_tasks[:20]  # 只返回最近20个
            ]
        }

    except Exception as e:
        logger.error(f"获取同步状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@app.get("/api/asmr-sync/waiting-retry")
async def asmr_sync_waiting_retry():
    """获取等待重试的任务列表及下次重试时间"""
    from ..core.task_engine import get_task_engine, TaskType
    from ..config.settings import get_config
    from datetime import datetime

    try:
        engine = get_task_engine()
        config = get_config()

        # 获取 cron 表达式
        cron_expr = "0 */1 * * *"  # 默认值
        if hasattr(config, 'asmr_sync') and config.asmr_sync:
            if hasattr(config.asmr_sync, 'retry_cron'):
                cron_expr = config.asmr_sync.retry_cron

        # 计算下次重试时间
        try:
            from croniter import croniter
            now = datetime.now()
            cron = croniter(cron_expr, now)
            next_retry_time = cron.get_next(datetime)
        except Exception as cron_err:
            logger.warning(f"解析cron表达式失败: {cron_err}, 使用默认值")
            next_retry_time = datetime.now()

        # 从数据库获取等待重试任务
        try:
            waiting_tasks = engine.get_waiting_retry_tasks_from_db()
        except Exception as db_err:
            logger.error(f"获取等待重试任务失败: {db_err}", exc_info=True)
            waiting_tasks = []

        return {
            "cron_expression": cron_expr,
            "next_retry_time": next_retry_time.isoformat(),
            "tasks": waiting_tasks
        }

    except Exception as e:
        logger.error(f"获取等待重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/pause")
async def asmr_sync_pause_task(task_id: str):
    """暂停任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.pause()
        return {"success": True, "message": "任务已暂停"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"暂停任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"暂停失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/resume")
async def asmr_sync_resume_task(task_id: str):
    """恢复任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        task.resume()
        return {"success": True, "message": "任务已恢复"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry")
async def asmr_sync_retry_failed(task_id: str):
    """重试失败的文件"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        task = engine.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        failed_files = task.task_metadata.get('failed_files', [])
        if not failed_files:
            return {"success": True, "message": "没有失败的文件需要重试"}

        # 清除失败文件列表，重新触发下载
        task.task_metadata['retry_failed'] = True
        task.resume()

        return {"success": True, "message": f"正在重试 {len(failed_files)} 个失败文件"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试失败文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.post("/api/asmr-sync/task/{task_id}/retry-waiting")
async def asmr_sync_retry_waiting_task(task_id: str):
    """手动重试等待中的任务（未找到版本的任务）"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()
        if engine.retry_task(task_id):
            return {"success": True, "message": "任务已加入重试队列"}
        else:
            raise HTTPException(status_code=400, detail="任务不在等待重试状态")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重试失败: {str(e)}")


@app.delete("/api/asmr-sync/task/{task_id}/waiting-retry")
async def asmr_sync_delete_waiting_retry_task(task_id: str):
    """删除等待重试的任务"""
    from ..core.task_engine import get_task_engine

    try:
        engine = get_task_engine()

        # 从内存中删除任务
        if task_id in engine.tasks:
            task = engine.tasks[task_id]
            rjcode = task.rjcode
            del engine.tasks[task_id]
            logger.info(f"[等待重试] 从内存中删除任务: {task_id}")

            # 从数据库中删除
            engine._remove_waiting_retry_task(rjcode)

            return {"success": True, "message": "任务已删除"}
        else:
            # 任务不在内存中，尝试从数据库删除
            engine._remove_waiting_retry_task_by_id(task_id)
            return {"success": True, "message": "任务已从数据库删除"}

    except Exception as e:
        logger.error(f"删除任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ========== 邮件监听 API ==========

class EmailWatcherTestRequest(BaseModel):
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"


@app.get("/api/email-watcher/status")
async def email_watcher_status():
    """返回邮件监听服务的当前状态。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    service = get_email_watcher_service()
    status = service.get_status()
    status["enabled"] = config.email_watcher.enabled
    if not config.email_watcher.enabled:
        status["mode"] = "disabled"
    return {"success": True, **status}


@app.post("/api/email-watcher/test")
async def email_watcher_test(request: EmailWatcherTestRequest):
    """测试 IMAP 连接是否正常。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    # 使用请求参数，如果为空则回退到已保存配置
    host = request.imap_host or config.email_watcher.imap_host
    port = request.imap_port or config.email_watcher.imap_port
    ssl = request.imap_ssl if request.imap_host else config.email_watcher.imap_ssl
    username = request.username or config.email_watcher.username
    password = request.password or config.email_watcher.password
    mailbox = request.mailbox or config.email_watcher.mailbox
    if not username or not password:
        raise HTTPException(status_code=400, detail="邮箱账号和密码不能为空")
    result = await get_email_watcher_service().test_connection(host, port, ssl, username, password, mailbox)
    return {"success": result.get("success", False), **result}


@app.post("/api/email-watcher/poll-now")
async def email_watcher_poll_now():
    """手动立即触发一次邮件检查（调试用）。"""
    from ..core.email_watcher_service import get_email_watcher_service
    config = get_config()
    if not config.email_watcher.enabled:
        raise HTTPException(status_code=400, detail="邮件监听未启用")
    if not config.email_watcher.username:
        raise HTTPException(status_code=400, detail="邮箱账号未配置")
    result = await get_email_watcher_service().poll_once()
    return result


# ========== 通知中心 API ==========

@app.get("/api/notifications/stream")
async def notifications_sse(request: Request):
    """SSE 实时通知推送流"""
    import json as _json
    from starlette.responses import StreamingResponse as _SR
    from ..core.task_notification_service import sse_subscribe, sse_unsubscribe

    loop = asyncio.get_event_loop()
    sid, q = sse_subscribe(loop)

    async def generator():
        try:
            yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_unsubscribe(sid)

    return _SR(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/notifications/unread-count")
async def notifications_unread_count():
    """获取未读通知数"""
    from ..core.task_notification_service import get_unread_count
    return {"count": get_unread_count()}


@app.get("/api/notifications")
async def list_notifications(
    page: int = 1,
    limit: int = 30,
    unread_only: bool = False,
):
    """获取通知列表"""
    from ..core.task_notification_service import list_notifications as _list
    return _list(page=page, limit=limit, unread_only=unread_only)


class NotificationReadRequest(BaseModel):
    ids: List[str]


@app.post("/api/notifications/read")
async def mark_notifications_read(body: NotificationReadRequest):
    """标记指定通知为已读"""
    from ..core.task_notification_service import mark_read
    count = mark_read(body.ids)
    return {"updated": count}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read():
    """标记全部通知为已读"""
    from ..core.task_notification_service import mark_all_read
    count = mark_all_read()
    return {"updated": count}


@app.delete("/api/notifications/{item_id}")
async def delete_notification(item_id: str):
    """删除单条通知"""
    from ..core.task_notification_service import delete_notification as _delete
    ok = _delete(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"ok": True}


class TestEmailRequest(BaseModel):
    config: Optional[dict] = None


@app.post("/api/notifications/test-email")
async def test_notification_email(body: TestEmailRequest):
    """测试 SMTP 发送配置"""
    from ..core.notification_email_service import test_smtp_connection
    cfg_dict = body.config or {}
    if not cfg_dict:
        config = get_config()
        cfg_dict = config.notification_email.model_dump()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, test_smtp_connection, cfg_dict)
    return result


# ---- 通知模板 API ----

@app.get("/api/notifications/templates")
async def list_notification_templates():
    """获取所有通知模板"""
    from ..core.notification_template_service import list_templates
    return {"items": list_templates()}


@app.post("/api/notifications/templates")
async def create_notification_template(request: Request):
    """创建通知模板"""
    from ..core.notification_template_service import create_template
    data = await request.json()
    return create_template(data)


@app.put("/api/notifications/templates/{template_id}")
async def update_notification_template(template_id: str, request: Request):
    """更新通知模板"""
    from ..core.notification_template_service import update_template
    data = await request.json()
    result = update_template(template_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="模板不存在")
    return result


@app.delete("/api/notifications/templates/{template_id}")
async def delete_notification_template(template_id: str):
    """删除通知模板"""
    from ..core.notification_template_service import delete_template
    ok = delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True}


class TemplatePreviewRequest(BaseModel):
    template_id: Optional[str] = None
    payload: Optional[dict] = None


@app.post("/api/notifications/templates/preview")
async def preview_notification_template(body: TemplatePreviewRequest):
    """预览模板渲染结果"""
    from ..core.notification_template_service import preview_template
    sample_payload = body.payload or {
        'event_type': 'completed',
        'title': '示例任务',
        'domain_label': '解压入库',
        'summary': '解压入库任务完成',
        'rjcode': 'RJ123456',
    }
    return preview_template(body.template_id, sample_payload)


# ---- Block 编辑器 API ----

@app.get("/api/notifications/blocks/schema")
async def get_blocks_schema():
    """返回 Block 类型 Schema、默认 props、属性定义和变量列表。"""
    from ..core.block_renderers import BLOCK_SCHEMA
    from ..core.variable_registry import VARIABLE_REGISTRY
    variables = [
        {"key": k, "label": v["label"], "example": v["example"]}
        for k, v in VARIABLE_REGISTRY.items()
    ]
    return {"blocks": BLOCK_SCHEMA, "variables": variables}


class PreviewBlocksRequest(BaseModel):
    requestId: Optional[str] = None
    blocks: list = []
    event_type: str = "completed"
    domain: str = "import"
    subject_template: Optional[str] = ""


@app.post("/api/notifications/templates/preview-blocks")
async def preview_notification_blocks(body: PreviewBlocksRequest):
    """用 blocks 数组 + 示例 payload 渲染预览 HTML，支持 requestId 校验乱序。"""
    from ..core.notification_template_service import preview_blocks
    result = preview_blocks(
        blocks=body.blocks,
        event_type=body.event_type,
        domain=body.domain,
        subject_template=body.subject_template or "",
    )
    return {"requestId": body.requestId, **result}



from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    # 返回项目根目录 (backend/app/api -> ../../../)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_base_path = get_base_path()

static_files_path = os.environ.get('STATIC_FILES_PATH', os.path.join(_base_path, "static"))
frontend_path = os.environ.get('FRONTEND_PATH', os.path.join(_base_path, "frontend", "dist"))

possible_paths = [
    frontend_path,
    static_files_path,
    os.path.join(_base_path, "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "../frontend/dist"),
    "/app/static",
]

frontend_build_path = None
logger.info(f"检查静态文件路径，当前工作目录: {os.getcwd()}")
logger.info(f"基础路径: {_base_path}")
for path in possible_paths:
    index_file = os.path.join(path, "index.html")
    path_exists = os.path.exists(path)
    index_exists = os.path.exists(index_file)
    logger.info(f"检查路径: {path} - 目录存在: {path_exists}, index.html存在: {index_exists}")
    if path_exists and index_exists:
        frontend_build_path = path
        logger.info(f"找到前端构建文件: {path}")
        break

# 注册静态文件服务（放在子路径，避免覆盖 API）
if frontend_build_path:
    # 提供静态资源文件（JS、CSS、图片等）
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_build_path, "assets")), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        favicon_path = os.path.join(frontend_build_path, "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path, media_type="image/x-icon")
        raise HTTPException(status_code=404, detail="Favicon not found")
    
    # 捕获所有非 API 路由，返回 index.html（SPA 支持）
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API 路由不应该被拦截
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # 对于前端路由，返回 index.html
        index_path = os.path.join(frontend_build_path, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")
