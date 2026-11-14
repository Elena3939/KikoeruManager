"""链接库后台导入、原子发布和固定修订下载。"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import tempfile
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text, update, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from ..models.database import SessionLocal, engine
from ..models.link_sheet import LinkSheetImport as Batch, LinkSheetRevision as Revision
from ..models.link_sheet import LinkSheetFile as File, LinkSheetCurrent as Current
from .link_sheet_parser import iter_records, normalize_code, digest, build_groups

logger = logging.getLogger(__name__)
SOURCE = "link_sheet"
IMPORT_LOCK = 730911091
PUBLISH_LOCK = 730911092


def upload_path(batch_id):
    from ..config.settings import get_config
    root = getattr(get_config().storage, "temp_path", "") or tempfile.gettempdir()
    return Path(root).resolve() / "kikoerumanager-link-sheet" / f"{batch_id}.xlsx"


def broadcast():
    from .realtime_event_service import broadcast_event
    broadcast_event({"type": "circle.resource_source.changed", "domain": "circle_completion",
                     "payload": {"source": SOURCE}})


def enqueue_changes(db, codes):
    """包含可信别名，登记和指针切换属于调用方的同一事务。"""
    if not codes:
        return []
    # 展开可信关联后和变更集合匹配，不生成“变更编号 × 所有社团”的脏事件。
    affected = db.execute(text("""
        SELECT x.circle_id, array_agg(DISTINCT x.code) AS codes FROM (
          SELECT w.circle_id, a.code FROM circle_works w
          CROSS JOIN LATERAL (
            SELECT w.canonical_rjcode AS code UNION SELECT w.display_rjcode
            UNION SELECT jsonb_array_elements_text(COALESCE(w.linked_rjcodes, '[]'::jsonb))
          ) a WHERE a.code=ANY(:codes)
          UNION SELECT a.circle_id, a.rjcode FROM circle_completion_work_aliases a
          JOIN circle_completion_heads h ON h.circle_id=a.circle_id AND h.active_generation=a.generation
          WHERE a.rjcode=ANY(:codes)
        ) x GROUP BY x.circle_id
    """), {"codes": codes}).all()
    from .circle_completion_changes import enqueue_in_session
    for circle, matched in affected:
        enqueue_in_session(db, [circle], matched, reason=SOURCE)
    return [circle for circle, _ in affected]


class ImportCancelled(Exception):
    pass


class LinkSheetService:
    def __init__(self):
        self.worker = None
        self.stopping = False
        self.submit_lock = asyncio.Lock()

    def create_import(self, batch_id, filename, sha):
        with SessionLocal.begin() as db:
            db.add(Batch(id=batch_id, file_name=filename, file_sha256=sha, status="queued",
                         statistics={}, error="", affected_circles=[], materialization_targets={}))

    def _flush(self, batch_id, records, stats):
        with SessionLocal.begin() as db:
            batch = db.get(Batch, batch_id, with_for_update=True)
            if batch.status == "cancelled" or self.stopping:
                raise ImportCancelled()
            codes = [r["rjcode"] for r in records]
            active = {code: (rid, fingerprint) for code, rid, fingerprint in
                      db.execute(select(Current.rjcode, Revision.id, Revision.content_hash)
                                    .join(Revision, Current.revision_id == Revision.id)
                                    .where(Current.rjcode.in_(codes))).all()}
            revisions, files = [], []
            for record in records:
                rid = uuid.uuid4().hex
                errors = record["errors"]
                previous_id, previous_hash = active.get(record["rjcode"], (None, None))
                kind = ("error" if errors else "unchanged" if previous_hash == record["content_hash"]
                        else "updated" if record["rjcode"] in active else "added")
                stats[kind] += 1
                revisions.append(dict(id=rid, import_id=batch_id, rjcode=record["rjcode"],
                    source_row=record["source_row"], content_hash=record["content_hash"],
                    metadata_json={} if kind == "unchanged" else record["metadata"],
                    groups=[] if kind == "unchanged" else record["groups"],
                    errors=errors, change_kind=kind,
                    reuse_revision_id=previous_id if kind == "unchanged" else None))
                # 未变项仅暂存旧修订引用，不再复制文件和资源组；确认时仍重查当前指针。
                if kind != "unchanged":
                    files.extend(dict(revision_id=rid, **file) for file in record["files"])
            if revisions:
                db.execute(insert(Revision), revisions)
            if files:
                db.execute(insert(File), files)
            stats["stored_works"] += len(revisions)
            batch.statistics = dict(stats)
            batch.updated_at = datetime.now()

    def parse(self, batch_id):
        stats = Counter()
        started = time.monotonic()
        records, seen, conflicting = [], {}, set()
        try:
            def counted(total):
                stats["total_works"] = total
                self._flush(batch_id, [], stats)

            for _, record in iter_records(upload_path(batch_id), on_total=counted):
                stats["rows"] += 1
                if record is None:
                    stats["skipped"] += 1
                    continue
                code = record["rjcode"]
                stats["rj_rows"] += 1
                stats["files"] += record.get("file_count", len(record["files"]))
                stats["par2"] += record.get("par2_count", sum(file["excluded"] for file in record["files"]))
                if code in seen:
                    if seen[code] != record["content_hash"]:
                        conflicting.add(code)
                    stats["duplicate_rows"] += 1
                    continue
                seen[code] = record["content_hash"]
                records.append(record)
                if len(records) >= 100:
                    self._flush(batch_id, records, stats)
                    records = []
            self._flush(batch_id, records, stats)
            with SessionLocal.begin() as db:
                batch = db.get(Batch, batch_id, with_for_update=True)
                if batch.status == "cancelled" or self.stopping:
                    raise ImportCancelled()
                if conflicting:
                    db.execute(update(Revision).where(Revision.import_id == batch_id,
                        Revision.rjcode.in_(conflicting)).values(
                            errors=["同一 RJ 在表内出现不同清单"], change_kind="error"))
                counts = db.execute(select(Revision.change_kind, func.count())
                                    .where(Revision.import_id == batch_id).group_by(Revision.change_kind)).all()
                for key in ("added", "updated", "unchanged", "error"):
                    stats[key] = dict(counts).get(key, 0)
                stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
                batch.statistics, batch.status = dict(stats), "ready"
                batch.updated_at = datetime.now()
        except ImportCancelled:
            with SessionLocal.begin() as db:
                batch = db.get(Batch, batch_id)
                if batch.status != "cancelled":
                    batch.status = "interrupted"
        except Exception as exc:
            from .log_sanitizer import sanitize_text_for_log
            with SessionLocal.begin() as db:
                batch = db.get(Batch, batch_id)
                if batch.status != "cancelled":
                    batch.status = "failed"
                    batch.error = sanitize_text_for_log(str(exc), max_length=400)
            logger.warning("链接表解析失败 batch=%s type=%s", batch_id, type(exc).__name__)
        finally:
            upload_path(batch_id).unlink(missing_ok=True)

    def _tick(self):
        # 会话锁覆盖整个解析，分块提交不会释放；其它进程不会误判活跃解析为中断。
        with engine.connect() as connection:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"),
                                          {"key": IMPORT_LOCK}).scalar()
            connection.commit()
            if not acquired:
                return
            try:
                with SessionLocal.begin() as db:
                    stale = db.scalars(select(Batch).where(Batch.status == "parsing")).all()
                    for row in stale:
                        row.status = "interrupted"
                        upload_path(row.id).unlink(missing_ok=True)
                    batch = db.scalar(select(Batch).where(Batch.status == "queued")
                                      .order_by(Batch.created_at).with_for_update(skip_locked=True).limit(1))
                    batch_id = batch.id if batch else None
                    if batch:
                        batch.status = "parsing"
                if batch_id:
                    self.parse(batch_id)
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": IMPORT_LOCK})
                connection.commit()

    def refresh_staged_size_validation(self):
        """重新核验待发布批次的大小、重名和分卷错误，不改已发布修订或任务。"""
        with SessionLocal.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLISH_LOCK})
            rows = db.execute(select(Revision, Batch).join(Batch, Revision.import_id == Batch.id)
                              .where(Batch.status == "ready", Revision.change_kind == "error")
                              .with_for_update()).all()
            affected = [(row, batch, [error for error in row.errors
                         if not re.fullmatch(r"第 \d+ 个文件(?:大小无效|存在同名冲突)", error)
                         and not re.fullmatch(r"资源组 .+ 存在重复(?:或不连续卷号|、不连续卷号或缺少 ZIP 主文件)", error)])
                        for row, batch in rows]
            affected = [(row, batch, errors) for row, batch, errors in affected if errors != row.errors]
            if not affected:
                return
            revisions = {row.id for row, _, _ in affected}
            stored_files = {}
            for file in db.scalars(select(File).where(File.revision_id.in_(revisions)).order_by(File.ordinal)):
                stored_files.setdefault(file.revision_id, []).append(dict(
                    id=file.id, name=file.name, size_bytes=file.size_bytes, excluded=file.excluded))
            codes = [row.rjcode for row, _, _ in affected]
            current = dict(db.execute(select(Current.rjcode, Revision.content_hash)
                                     .join(Revision, Current.revision_id == Revision.id)
                                     .where(Current.rjcode.in_(codes))).all())
            batches = {}
            for row, batch, errors in affected:
                groups, group_errors = build_groups(stored_files.get(row.id, []))
                row.groups = groups
                errors = list(dict.fromkeys([*errors, *group_errors]))
                row.errors = errors
                row.change_kind = ("error" if errors else "unchanged" if current.get(row.rjcode) == row.content_hash
                                   else "updated" if row.rjcode in current else "added")
                batches[batch.id] = batch
            db.flush()
            counts = db.execute(select(Revision.import_id, Revision.change_kind, func.count())
                                .where(Revision.import_id.in_(batches))
                                .group_by(Revision.import_id, Revision.change_kind)).all()
            totals = {(bid, kind): count for bid, kind, count in counts}
            for bid, batch in batches.items():
                batch.statistics = {**batch.statistics, **{kind: totals.get((bid, kind), 0)
                                    for kind in ("added", "updated", "unchanged", "error")}}
                batch.updated_at = datetime.now()

    async def start(self):
        if self.worker and not self.worker.done():
            return
        self.stopping = False
        await asyncio.to_thread(self.refresh_staged_size_validation)

        async def run():
            while not self.stopping:
                try:
                    await asyncio.to_thread(self._tick)
                except Exception:
                    logger.exception("链接表后台任务失败")
                await asyncio.sleep(2)
        self.worker = asyncio.create_task(run())

    async def stop(self):
        self.stopping = True
        if self.worker:
            await self.worker
            self.worker = None

    def cancel(self, batch_id):
        with SessionLocal.begin() as db:
            batch = db.get(Batch, batch_id, with_for_update=True)
            if not batch:
                raise ValueError("导入批次不存在")
            if batch.status == "published":
                raise ValueError("已发布批次不能取消")
            batch.status = "cancelled"
        # 活跃解析在分块检查时清理；已完成的上传文件也在此回收。
        try:
            upload_path(batch_id).unlink(missing_ok=True)
        except PermissionError:
            pass

    def confirm(self, batch_id):
        with SessionLocal.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLISH_LOCK})
            batch = db.get(Batch, batch_id, with_for_update=True)
            if not batch:
                raise ValueError("导入批次不存在")
            if batch.status == "published":
                return self.batch(batch_id)
            if batch.status != "ready":
                raise ValueError("仅已完成解析的批次可以发布")
            rows = db.execute(select(Revision.id, Revision.rjcode, Revision.errors, Revision.content_hash,
                                     Revision.reuse_revision_id)
                              .where(Revision.import_id == batch_id)).all()
            current = dict(db.execute(select(Current.rjcode, Revision.content_hash)
                                      .join(Revision, Current.revision_id == Revision.id)).all())
            changed, redundant = [], []
            counts = Counter()
            pointers = []
            for row in rows:
                kind = ("error" if row.errors else "unchanged" if current.get(row.rjcode) == row.content_hash
                        else "updated" if row.rjcode in current else "added")
                counts[kind] += 1
                if kind == "unchanged" or (row.reuse_revision_id and kind != "error"):
                    redundant.append(row.id)
                if kind in {"added", "updated"}:
                    pointers.append(dict(rjcode=row.rjcode, revision_id=row.reuse_revision_id or row.id, enabled=True))
                    changed.append(row.rjcode)
            for offset in range(0, len(pointers), 1000):
                statement = insert(Current).values(pointers[offset:offset + 1000])
                # 保留用户停用态；只有首次出现的 RJ 默认启用。
                db.execute(statement.on_conflict_do_update(index_elements=[Current.rjcode],
                           set_={"revision_id": statement.excluded.revision_id}))
            # 一次性读取整批仍被 current 引用的修订，避免每 1000 条删除批次
            # 额外执行一次查询；大清单发布保持固定 1 次保护查询。
            referenced_ids = set(db.scalars(
                select(Current.revision_id).where(Current.revision_id.in_(redundant))
            ).all()) if redundant else set()
            for offset in range(0, len(redundant), 1000):
                ids = redundant[offset:offset + 1000]
                # 确认请求可能因前端超时被重复提交。第一次提交已经切换
                # current 指针时，第二次会把这些修订识别为 unchanged；删除前
                # 必须保护仍被 current 引用的修订，否则会触发外键 500。
                deletable_ids = [revision_id for revision_id in ids if revision_id not in referenced_ids]
                if not deletable_ids:
                    continue
                db.execute(delete(File).where(File.revision_id.in_(deletable_ids)))
                db.execute(delete(Revision).where(Revision.id.in_(deletable_ids)))
            batch.affected_circles = enqueue_changes(db, changed)
            batch.materialization_targets = dict(db.execute(text(
                "SELECT circle_id, requested_seq FROM circle_completion_controls WHERE circle_id=ANY(:circles)"
            ), {"circles": batch.affected_circles}).all()) if batch.affected_circles else {}
            batch.statistics = {**batch.statistics, **counts, "changed_works": len(changed)}
            batch.status, batch.updated_at = "published", datetime.now()
        broadcast()
        return self.batch(batch_id)

    def batch(self, batch_id):
        with SessionLocal() as db:
            batch = db.get(Batch, batch_id)
            if not batch:
                raise ValueError("导入批次不存在")
            pending, failed = 0, 0
            if batch.materialization_targets:
                state = db.execute(text("""
                    SELECT count(*) FILTER (WHERE t.seq>COALESCE(h.applied_seq,0)) AS pending,
                           count(*) FILTER (WHERE t.seq>COALESCE(h.applied_seq,0)
                             AND COALESCE(c.last_error,'')<>'') AS failed
                    FROM jsonb_each_text(CAST(:targets AS jsonb)) AS v(key,value)
                    CROSS JOIN LATERAL (SELECT v.key AS circle_id, v.value::bigint AS seq) t
                    LEFT JOIN circle_completion_controls c USING(circle_id)
                    LEFT JOIN circle_completion_heads h USING(circle_id)
                """), {"targets": json.dumps(batch.materialization_targets)}).mappings().one()
                pending, failed = state["pending"], state["failed"]
            from .log_sanitizer import mask_urls_in_data
            return dict(id=batch.id, file_name=mask_urls_in_data(batch.file_name), status=batch.status,
                        statistics=batch.statistics, error=mask_urls_in_data(batch.error),
                        created_at=batch.created_at.isoformat(),
                        materialization_status="failed" if failed else "updating" if pending else
                        "ready" if batch.status == "published" else "pending")

    def history(self, page=1):
        with SessionLocal() as db:
            ids = db.scalars(select(Batch.id).order_by(Batch.created_at.desc())
                             .offset((page - 1) * 20).limit(20)).all()
        return [self.batch(batch_id) for batch_id in ids]

    def works(self, page=1, search="", batch_id="", errors_only=False, page_size=10):
        if not 1 <= page_size <= 100:
            raise ValueError("每页条数必须为 1 到 100")
        with SessionLocal() as db:
            reused = aliased(Revision)
            metadata = func.coalesce(reused.metadata_json, Revision.metadata_json)
            groups = func.coalesce(reused.groups, Revision.groups)
            statement = (select(Revision, Current.enabled, metadata.label("metadata"), groups.label("groups"))
                         .outerjoin(Current, Current.revision_id == Revision.id)
                         .outerjoin(reused, reused.id == Revision.reuse_revision_id))
            if batch_id:
                statement = statement.where(Revision.import_id == batch_id)
            else:
                statement = statement.where(Current.rjcode.is_not(None))
            if search:
                term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                statement = statement.where(Revision.rjcode.ilike(term) |
                    metadata.op("->>")("标题").ilike(term))
            if errors_only:
                statement = statement.where(Revision.change_kind == "error")
            total = db.scalar(select(func.count()).select_from(statement.subquery()))
            page = min(max(1, page), max(1, (total + page_size - 1) // page_size))
            rows = db.execute(statement.order_by(Revision.source_row, Revision.rjcode)
                              .offset((page - 1) * page_size).limit(page_size)).all()
            from .log_sanitizer import mask_urls_in_data
            return mask_urls_in_data(dict(total=total, page=page, page_size=page_size, items=[
                dict(id=r.id, rjcode=r.rjcode, title=meta.get("标题", ""), enabled=enabled,
                     source_row=r.source_row, change_kind=r.change_kind, errors=r.errors,
                     group_count=len(resource_groups)) for r, enabled, meta, resource_groups in rows]))

    def plan(self, code):
        code = normalize_code(code)
        return self.plans([code]).get(code)

    def plans(self, codes):
        """按批 JOIN 当前指针与修订，不读取文件链接，不缓存可变发布指针。"""
        codes = list(dict.fromkeys(code for value in codes if (code := normalize_code(value))))
        if not codes:
            return {}
        plans = {}
        from .http_download_service import get_http_download_service
        from .log_sanitizer import mask_urls_in_data
        download_root = get_http_download_service()._download_root()
        with SessionLocal() as db:
            for offset in range(0, len(codes), 500):
                rows = db.execute(select(Current.rjcode, Revision.id, Revision.metadata_json, Revision.groups)
                    .join(Revision, Revision.id == Current.revision_id)
                    .where(Current.enabled.is_(True), Current.rjcode.in_(codes[offset:offset + 500]))).all()
                for code, revision_id, metadata, stored_groups in rows:
                    groups = copy.deepcopy(stored_groups)
                    for group in groups:
                        group.update(rjcode=code, relative_path=f"{group['name']} · {group['archive_name']}",
                                     file_name=group["archive_name"], selected=False)
                        for file in group["files"]:
                            file["selected_candidate_id"] = file["candidate_ids"][0]
                    plans[code] = mask_urls_in_data(dict(rjcode=code, source_provider=SOURCE, revision_id=revision_id,
                        download_root=download_root, title=metadata.get("标题", code), selectable_resources=groups,
                        total_size_bytes=sum(group["size_bytes"] for group in groups),
                        selected_resource_count=0, selected_size_bytes=0, filtered_out_resources=[]))
        return plans

    def detail(self, revision_id):
        with SessionLocal() as db:
            row = db.get(Revision, revision_id)
            if not row:
                raise ValueError("修订不存在")
            errors = row.errors
            if row.reuse_revision_id:
                row = db.get(Revision, row.reuse_revision_id)
            files = db.scalars(select(File).where(File.revision_id == row.id).order_by(File.ordinal)).all()
            file_groups = {
                candidate_id: group["id"]
                for group in (row.groups or [])
                for logical in group.get("files", [])
                for candidate_id in logical.get("candidate_ids", [])
            }
            # 管理详情允许查看完整清单；下载任务和公共事件继续走各自的脱敏路径。
            return dict(id=row.id, rjcode=row.rjcode, metadata=row.metadata_json, groups=row.groups,
                        errors=errors, files=[dict(id=f.id, name=f.name, size_bytes=f.size_bytes,
                        raw_size=f.raw_size, ordinal=f.ordinal, excluded=f.excluded, url=f.url,
                        group_id=file_groups.get(f.id)) for f in files])

    async def download_revision(self, revision_id, group_id=""):
        """把修订中的可下载资源交给统一 HTTP/MEGA 任务引擎。"""
        with SessionLocal() as db:
            row = db.get(Revision, revision_id)
            if not row:
                raise ValueError("链接库修订不存在")
            groups = [group for group in (row.groups or [])
                      if (not group_id or group.get("id") == group_id)
                      and not group.get("excluded") and group.get("complete", True)]
            item = {
                "source_provider": SOURCE,
                "rjcode": row.rjcode,
                "revision_id": row.id,
                "selected_resources": [{
                    "id": group["id"],
                    "candidate_ids": [file["candidate_ids"][0] for file in group.get("files", [])],
                } for group in groups],
            }
        if not item["selected_resources"]:
            raise ValueError("该修订没有可下载资源组")
        return await self.submit(item, "link-sheet-settings")

    def set_enabled(self, code, enabled):
        with SessionLocal.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLISH_LOCK})
            row = db.get(Current, normalize_code(code))
            if not row:
                raise ValueError("作品不存在")
            row.enabled = enabled
            enqueue_changes(db, [row.rjcode])
        broadcast()

    def validate_item(self, item):
        plan = self.plan(item.get("rjcode"))
        if not plan or plan["revision_id"] != item.get("revision_id"):
            raise ValueError("链接库清单已变化或已停用，请刷新后选择")
        available = {g["id"]: g for g in plan["selectable_resources"]}
        selected = item.get("selected_resources") or []
        if not selected or len({g.get("id") for g in selected}) != len(selected):
            raise ValueError("请选择不重复的资源组")
        groups = []
        for selection in selected:
            group = available.get(selection.get("id"))
            if not group:
                raise ValueError("所选资源组不属于当前修订")
            if not group.get("complete", True):
                raise ValueError("所选分卷方案不完整，请核对文件")
            choices = selection.get("candidate_ids")
            if choices is None:
                choices = [f["candidate_ids"][0] for f in group["files"]]
            if len(choices) != len(group["files"]) or any(
                    choice not in file["candidate_ids"] for choice, file in zip(choices, group["files"])):
                raise ValueError("文件候选不属于所选资源组")
            groups.append({**group, "selected_candidate_ids": choices})
        return plan, groups

    @asynccontextmanager
    async def submission_guard(self):
        def acquire():
            db = SessionLocal()
            try:
                db.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": PUBLISH_LOCK})
                return db
            except BaseException:
                db.close()
                raise
        pending = asyncio.create_task(asyncio.to_thread(acquire))
        try:
            db = await asyncio.shield(pending)
        except asyncio.CancelledError:
            db = await pending
            await asyncio.to_thread(db.close)
            raise
        try:
            yield
        finally:
            await asyncio.to_thread(db.close)

    async def submit(self, item, source_page, context=None, validated=None):
        from .task_engine import Task, TaskType, get_task_engine
        # 校验与持久化提交期间阻止其它进程发布/停用，已提交任务仍固定旧修订。
        async with self.submit_lock, self.submission_guard():
            plan, groups = await asyncio.to_thread(self.validate_item, item)
            engine_instance = get_task_engine()
            tasks = []
            for group in groups:
                key = "link_sheet:" + digest([plan["revision_id"], group["id"], group["selected_candidate_ids"]])
                task = next((t for t in engine_instance.tasks.values()
                             if t.task_metadata.get("business_key") == key
                             and t.status.value in {"pending", "processing", "paused"}), None)
                if task is None:
                    task = Task(task_type=TaskType.HTTP_DOWNLOAD, source_path=plan["rjcode"],
                        rjcode=plan["rjcode"], metadata={
                            **dict(context or {}), "resource_source": SOURCE,
                            "link_sheet_revision_id": plan["revision_id"], "resource_group_id": group["id"],
                            "link_sheet_file_ids": group["selected_candidate_ids"], "business_key": key,
                            "source_page": source_page, "source_action": "link_sheet_download",
                            "work_title": plan["title"], "rjcode": plan["rjcode"],
                            "download_mode": SOURCE, "task_kind": "http_download",
                            "task_domain": "circle_completion" if source_page == "circle-completion" else "http_download",
                            "conflict_policy": "resume", "http_download_auto_retry_limit": 2})
                    def persist():
                        with SessionLocal.begin() as db:
                            engine_instance.write_task_snapshot(db, task)
                    # 先持久化固定引用，再交给现有任务引擎，避免提交成功后立即重启丢任务。
                    await asyncio.to_thread(persist)
                    await engine_instance.submit(task)
                tasks.append(dict(task_id=task.id, rjcode=plan["rjcode"], source_provider=SOURCE))
            return tasks

    def task_files(self, metadata):
        with SessionLocal() as db:
            revision = db.get(Revision, metadata.get("link_sheet_revision_id"))
            group = next((g for g in revision.groups if g["id"] == metadata.get("resource_group_id")), None) if revision else None
            ids = metadata.get("link_sheet_file_ids") or []
            if not group or len(ids) != len(group["files"]) or any(
                    choice not in file["candidate_ids"] for choice, file in zip(ids, group["files"])):
                raise ValueError("任务绑定的链接库清单无效")
            files = {f.id: f for f in db.scalars(select(File).where(File.revision_id == revision.id, File.id.in_(ids)))}
            return dict(rjcode=revision.rjcode, revision_id=revision.id, group_id=group["id"],
                        group_name=group["name"], files=[dict(id=key, name=files[key].name,
                        save_name=logical.get("save_name", files[key].name),
                        size_bytes=files[key].size_bytes, url=files[key].url)
                        for key, logical in zip(ids, group["files"])])


_service = LinkSheetService()


def get_link_sheet_service():
    return _service
