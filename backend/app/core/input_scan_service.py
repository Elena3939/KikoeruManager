"""持久扫描协调者：发现、到期观察、可靠交接分别推进。"""

import asyncio
import logging
import os
import time
from collections import OrderedDict

from ..config.settings import get_config
from ..models.database import get_local_now
from .input_scan_discovery import InputScanDiscovery
from .input_scan_repository import InputScanRepository, SourceChanged, SourceOccupied
from .input_stability import observe_sources
from .task_engine import Task, TaskStatus, TaskType, get_task_engine

logger = logging.getLogger(__name__)
SCAN_TERMINAL = {"completed", "cancelled", "failed"}


async def finish_thread(function, *args, **kwargs):
    """取消不能留下仍在写账本或检查文件的线程。"""
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await work
        raise


class InputScanService:
    def __init__(self, repository=None):
        self.repository = repository or InputScanRepository()
        self._task = None
        self._maintenance = None
        self._start_lock = asyncio.Lock()
        self._schedule_lock = asyncio.Lock()
        self._active_id = None
        self._revisions = {}
        self._observations = OrderedDict()
        self._background_runs = {}
        self._checking_ids = set()
        self._preflights = OrderedDict()

    async def accept_watch_file(self, file_path):
        """监听事件只登记候选，稳定等待和提交复用扫描账本。"""
        from .file_processor import FileProcessor
        from .input_scan_repository import path_key
        from .input_stability import sample_sources

        def group_source():
            processor = FileProcessor()
            volume = processor.detect_volume_set(file_path)
            source = volume.entry_path if volume else file_path
            identity = os.path.join(
                os.path.dirname(source), volume.base_name + "\0" + volume.type,
            ) if volume else source
            group = {
                "group_key": path_key(identity), "source_path": source,
                "members": volume.volumes if volume else [source], "needs_stability": True,
            }
            try:
                group["fingerprints"], _ = sample_sources(group["members"])
            except OSError:
                group["fingerprints"] = None
            return group

        group = await finish_thread(group_source)
        async with self._start_lock:
            config = get_config()
            policy = {
                "source_page": "watcher", "source_action": "watch_input",
                "event_driven": True, "auto_classify": config.watcher.auto_classify,
            }
            scan_id = await finish_thread(
                self.repository.create_run, config.storage.input_path, policy,
            )
            existing = await finish_thread(
                self.repository.find_candidate_for_group, scan_id, group["group_key"],
            )
            if existing and existing["state"] in {"submitted", "routed", "skipped", "failed", "cancelled"}:
                previous = existing["evidence"].get("fingerprints")
                if not previous or previous != group["fingerprints"]:
                    scan_id = await finish_thread(
                        self.repository.create_run, config.storage.input_path, policy, force_new=True,
                    )
            await finish_thread(
                self.repository.discover, scan_id, [group], config.input_scan.stable_timeout_seconds,
            )
            worker = self._background_runs.get(scan_id)
            if worker is None or worker.done():
                self._background_runs[scan_id] = asyncio.create_task(
                    self._run(scan_id), name=f"input-watch:{scan_id}",
                )
            self._ensure_maintenance()
        while True:
            candidate = await finish_thread(
                self.repository.candidate_for_group, scan_id, group["group_key"],
            )
            if candidate["task_id"]:
                engine = get_task_engine()
                await engine.enqueue_once(candidate["task_id"])
                task = engine.get_task(candidate["task_id"])
                if task is not None:
                    return task
            if candidate["state"] in {"skipped", "failed", "cancelled"}:
                return None
            worker = self._background_runs.get(scan_id)
            if worker is None or worker.done():
                snapshot = await self.get(scan_id)
                if snapshot["status"] in SCAN_TERMINAL | {"interrupted"}:
                    return None
            await asyncio.sleep(0.5)

    async def start(self, *, request_key=None, target_library_id=None, source_action="scan_input"):
        async with self._start_lock:
            config = get_config()
            root = config.storage.input_path
            await finish_thread(os.makedirs, root, exist_ok=True)
            policy = {
                "source_page": "dashboard", "source_action": source_action,
                "auto_classify": config.watcher.auto_classify,
                "target_library_id": target_library_id,
            }
            scan_id = await finish_thread(self.repository.create_run, root, policy, request_key)
            snapshot = await self.get(scan_id)
            if snapshot["status"] not in SCAN_TERMINAL and (
                self._task is None or self._task.done()
            ):
                self._active_id = scan_id
                self._task = asyncio.create_task(self._run(scan_id), name="input-scan")
            self._ensure_maintenance()
            return snapshot

    async def get(self, scan_id):
        return await finish_thread(self.repository.snapshot, scan_id)

    async def latest(self):
        ids = await finish_thread(self.repository.runs, 1)
        return await self.get(ids[0]) if ids else None

    async def recover(self):
        """单进程重启后重枚举未闭合目录；候选身份及派发意图保持不变。"""
        await finish_thread(self.repository.reconcile_sources)
        ids = await finish_thread(self.repository.recoverable)
        for scan_id in ids:
            snapshot = await self.get(scan_id)
            if snapshot["policy"].get("event_driven"):
                self._background_runs[scan_id] = asyncio.create_task(
                    self._run(scan_id), name=f"input-watch-recovery:{scan_id}",
                )
            else:
                self._active_id = scan_id
                self._task = asyncio.create_task(self._run(scan_id), name="input-scan-recovery")
        for task_id in await finish_thread(self.repository.pending_tasks):
            await get_task_engine().enqueue_once(task_id)
        self._ensure_maintenance()

    def _ensure_maintenance(self):
        if self._maintenance is None or self._maintenance.done():
            self._maintenance = asyncio.create_task(self._maintain(), name="input-scan-outbox")

    async def cancel(self, scan_id):
        return await finish_thread(self.repository.cancel, scan_id)

    async def _publish(self, scan_id):
        snapshot = await finish_thread(self.repository.snapshot, scan_id, materialize=True)
        if snapshot and self._revisions.get(scan_id) != snapshot["revision"]:
            from .realtime_event_service import broadcast_event
            await finish_thread(broadcast_event, {
                "type": "input.scan.changed", "id": scan_id,
                "domain": "input_scan", "status": snapshot["status"], "payload": snapshot,
            })
            self._revisions[scan_id] = snapshot["revision"]
        return snapshot

    async def _maintain(self):
        while True:
            try:
                from .resource_budget_service import get_resource_budget_service
                await get_resource_budget_service().refresh()
                engine = get_task_engine()
                await engine.refresh_input_metadata_window()
                for task in engine.get_all_tasks():
                    if getattr(task, "_input_lifecycle_pending", False):
                        await finish_thread(engine.persist_task_snapshot, task)
                for event in await finish_thread(self.repository.outbox):
                    try:
                        if event["kind"] == "task_lifecycle":
                            await finish_thread(self.repository.deliver_lifecycle, event["id"])
                            continue
                        if event["kind"] == "scan_notification":
                            from .task_notification_service import write_input_scan_notification
                            await finish_thread(
                                write_input_scan_notification, event["scan_id"],
                                repository=self.repository,
                            )
                            await finish_thread(self.repository.acknowledge, event["id"])
                            continue
                        if event["kind"] not in {"task_dispatch", "task_restore"}:
                            raise ValueError(f"未知扫描交接事件: {event['kind']}")
                        await get_task_engine().enqueue_once(event["payload"]["task_id"])
                    except Exception as exc:
                        await finish_thread(self.repository.acknowledge, event["id"], exc)
                        logger.warning("扫描任务派发失败，将重试: %s", event["id"], exc_info=True)
                    else:
                        await finish_thread(self.repository.acknowledge, event["id"])
                watching = await finish_thread(self.repository.unsettled_runs)
                for scan_id in watching:
                    await self._publish(scan_id)
                self._revisions = {
                    key: value for key, value in self._revisions.items() if key in watching
                }
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("扫描交接维护失败")
            await asyncio.sleep(max(0.5, get_config().input_scan.progress_interval_seconds))

    async def _run(self, scan_id):
        discovery = None
        receiver = None
        checks = {}
        try:
            await self._cleanup_stages(scan_id)
            await finish_thread(self.repository.resume, scan_id)
            snapshot = await self.get(scan_id)
            event_driven = snapshot["policy"].get("event_driven", False)
            if not event_driven and not snapshot["producer_closed"] and not snapshot["cancel_requested"]:
                discovery = InputScanDiscovery(
                    snapshot["root_path"], get_config().input_scan.discovery_queue_capacity,
                    repository=self.repository, scan_id=scan_id,
                )
                await discovery.start()
                receiver = asyncio.create_task(discovery.receive())
            next_check = 0
            while True:
                for candidate_id, work in list(checks.items()):
                    if work.done():
                        del checks[candidate_id]
                        self._checking_ids.discard(candidate_id)
                        work.result()
                if receiver:
                    done, _ = await asyncio.wait({receiver}, timeout=0.1)
                    if done:
                        message = receiver.result()
                        if message.get("closed"):
                            await finish_thread(
                                self.repository.close_producer, scan_id,
                                reason="error" if message["errors"] else "exhausted",
                                errors=message["errors"], enumerated_files=message["enumerated_files"],
                            )
                            receiver = None
                        else:
                            await finish_thread(
                                self.repository.discover, scan_id, message["groups"],
                                get_config().input_scan.stable_timeout_seconds,
                            )
                            receiver = asyncio.create_task(discovery.receive())
                else:
                    await asyncio.sleep(0.1)
                if time.monotonic() < next_check:
                    continue
                snapshot = await finish_thread(self.repository.control_state, scan_id)
                if snapshot["cancel_requested"]:
                    break
                if event_driven and not snapshot["pending_count"] and not checks:
                    # 与事件登记使用同一进程锁，避免生产关闭和新事件相互穿过。
                    async with self._start_lock:
                        if await finish_thread(self.repository.close_event_producer, scan_id):
                            break
                if snapshot["producer_closed"] and not snapshot["pending_count"] and not checks:
                    break
                async with self._schedule_lock:
                    config = get_config()
                    available = min(
                        max(1, config.processing.max_workers),
                        config.input_scan.active_candidate_limit,
                    ) - len(self._checking_ids)
                    if available <= 0:
                        continue
                    now = time.monotonic()
                    # 高频采样证据只保留有界工作集，持久化期限用于公平轮转。
                    excluded = [
                        key for key, value in self._observations.items()
                        if value["due"] > now
                    ]
                    excluded.extend(self._checking_ids)
                    candidates = await finish_thread(
                        self.repository.due, scan_id, available, excluded,
                    )
                    for candidate in candidates:
                        self._checking_ids.add(candidate["id"])
                        checks[candidate["id"]] = asyncio.create_task(
                            self._check(candidate, snapshot["policy"]),
                            name=f"input-check:{candidate['id']}",
                        )
                next_check = time.monotonic() + 0.2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("输入扫描失败: %s", scan_id)
            await finish_thread(
                self.repository.close_producer, scan_id, reason="error",
                errors=[{"reason": str(exc)}],
            )
        finally:
            for work in checks.values():
                if not work.done():
                    work.cancel()
            await asyncio.gather(*checks.values(), return_exceptions=True)
            self._checking_ids.difference_update(checks)
            for candidate_id in checks:
                self._preflights.pop(candidate_id, None)
            for candidate_id, prepared in list(self._preflights.items()):
                if prepared["scan_id"] == scan_id:
                    self._preflights.pop(candidate_id, None)
            if receiver is not None:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
            if discovery:
                try:
                    await discovery.stop()
                except Exception:
                    logger.exception("目录发现线程退出异常: %s", scan_id)
            await self._cleanup_stages(scan_id)
            snapshot = await self.get(scan_id)
            if snapshot["cancel_requested"]:
                await finish_thread(self.repository.finish_cancel, scan_id)
            elif snapshot["status"] != "failed" and (
                not snapshot["producer_closed"] or snapshot["pending_count"]
            ):
                await finish_thread(self.repository.finish_cancel, scan_id, interrupted=True)
            await self._publish(scan_id)
            self._background_runs.pop(scan_id, None)

    async def _check(self, candidate, policy):
        from .resource_budget_service import get_resource_budget_service
        from .input_preflight import policy_revision, index_view_token, stage_preparer
        engine = get_task_engine()
        acquired = False
        task = None
        config = get_config()
        try:
            cached = self._observations.get(candidate["id"])
            if cached and cached["version"] == candidate["version"]:
                candidate["evidence"] = cached["evidence"]
            if candidate["state"] != "ready" and candidate["deadline"] and candidate["deadline"] < get_local_now():
                await self._update(candidate, state="failed", reason="source_not_stable")
                return
            async with get_resource_budget_service().acquire("disk_io_local", reason="输入扫描采样"):
                evidence, reason = await finish_thread(
                    observe_sources, candidate["members"], candidate["evidence"],
                    checks=max(1, config.processing.file_stable_checks),
                    interval=max(0.1, config.processing.file_stable_interval),
                    needs_stability=bool(candidate["evidence"].get("needs_stability")),
                )
            if reason:
                interval = max(0.1, config.processing.file_stable_interval)
                if not cached or cached["version"] != candidate["version"] or candidate["reason"] != reason:
                    if not await self._update(
                        candidate, state="waiting_stable", reason=reason, evidence=evidence,
                        delay=interval,
                    ):
                        return
                elif time.monotonic() - cached["checkpoint"] >= 30:
                    if not await self._update(
                        candidate, state="waiting_stable", reason=reason, evidence=evidence, delay=interval,
                    ):
                        return
                else:
                    self._observations[candidate["id"]] = {
                        **cached, "evidence": evidence, "due": time.monotonic() + interval,
                    }
                    return
                self._observations[candidate["id"]] = {
                    "version": candidate["version"], "evidence": evidence,
                    "due": time.monotonic() + interval, "checkpoint": time.monotonic(),
                }
                while len(self._observations) > config.input_scan.active_candidate_limit:
                    self._observations.popitem(last=False)
                return
            self._observations.pop(candidate["id"], None)
            if not engine.try_acquire_input_preflight(candidate["id"]):
                await self._update(
                    candidate, state="ready", reason="preflight_capacity", evidence=evidence, delay=1,
                )
                return
            acquired = True
            if not await self._update(candidate, state="preflight", evidence=evidence):
                return
            if not await finish_thread(self.repository.claim, candidate["id"], candidate["version"]):
                return
            # 后续异常必须使用最新版本，避免变化源永远卡在旧证据。
            candidate["evidence"] = evidence
            task = Task(
                TaskType.AUTO_PROCESS, candidate["source_path"],
                auto_classify=bool(config.watcher.auto_classify),
                metadata={
                    "source_page": policy.get("source_page", "dashboard"),
                    "source_action": policy.get("source_action", "scan_input"),
                    "target_library_id": policy.get("target_library_id"),
                    "input_members": candidate["members"],
                    "input_stability": evidence,
                },
            )
            from .file_processor import get_file_processor
            task.task_metadata.update(
                get_file_processor()._inherit_download_password_metadata(
                    candidate["source_path"], get_task_engine(),
                ),
            )
            from .extract_service import ExtractService
            from .classifier import SmartClassifier
            revision, view = policy_revision(config), index_view_token()
            prepared = self._preflights.pop(candidate["id"], None)
            reusable = prepared and (
                prepared["revision"] == revision and prepared["view"] == view
                and prepared["fingerprints"] == evidence["fingerprints"]
                and time.monotonic() - prepared["at"] <= 30
            )
            if reusable:
                task, rjcode, proceed = prepared["task"], prepared["rjcode"], True
            else:
                task._prepared_conflicts = []
                context = stage_preparer.set(
                    lambda path: self.repository.prepare_stage(candidate["id"], candidate["version"], path),
                )
                from .input_source_rename import InputSourceRenamer, source_rename_handler
                rename_context = source_rename_handler.set(
                    InputSourceRenamer(self.repository, candidate, task),
                )
                try:
                    extract_service = ExtractService()
                    task.source_path = await extract_service.normalize_archive_filename(task.source_path)
                    evidence = candidate["evidence"]
                    rjcode, proceed = await engine._preflight_auto_process(
                        task, extract_service, SmartClassifier(prepared_conflicts=task._prepared_conflicts), config,
                    )
                finally:
                    source_rename_handler.reset(rename_context)
                    stage_preparer.reset(context)
            if revision != policy_revision(get_config()) or view != index_view_token():
                await self._update(
                    candidate, state="ready", reason="preflight_evidence_changed", delay=0.2,
                )
                return
            task.task_metadata["input_preflight"] = {
                "version": 1, "policy_revision": revision, "index_view_token": view,
                "rjcode": rjcode,
                "checked_at": prepared["checked_at"] if reusable else get_local_now().isoformat(),
                "fingerprints": evidence["fingerprints"], "proceed": proceed,
            }
            if proceed:
                self._preflights[candidate["id"]] = {
                    "task": task, "rjcode": rjcode, "revision": revision, "view": view,
                    "fingerprints": evidence["fingerprints"],
                    "at": prepared["at"] if reusable else time.monotonic(),
                    "checked_at": task.task_metadata["input_preflight"]["checked_at"],
                    "scan_id": candidate["scan_id"],
                }
                while len(self._preflights) > config.input_scan.active_candidate_limit:
                    self._preflights.popitem(last=False)
            if proceed and not self._has_handoff_capacity(config):
                await self._update(
                    candidate, state="ready", reason="engine_backpressure", evidence=evidence, delay=1,
                )
                return
            if proceed:
                # 预检进度不应成为尚未开始的正式任务进度。
                task.status, task.progress, task.current_step = TaskStatus.PENDING, 0, "等待中"
            committed = await finish_thread(
                self.repository.commit_candidate, candidate["id"], candidate["version"], task,
                pending_limit=2 * max(1, config.processing.max_workers),
                routed=not proceed, prepared_conflicts=task._prepared_conflicts,
            )
            if committed:
                self._preflights.pop(candidate["id"], None)
        except asyncio.CancelledError:
            if task is not None:
                task.cancel()
            raise
        except SourceOccupied as exc:
            await self._update(
                candidate, state="skipped", reason=f"{exc.owner_type}:{exc.owner_id}",
            )
        except (OSError, SourceChanged) as exc:
            await self._update(
                candidate, state="waiting_stable", reason=str(exc)[:500],
                evidence={"needs_stability": candidate["evidence"].get("needs_stability", True)},
                delay=max(0.1, config.processing.file_stable_interval),
                stable_timeout=config.input_scan.stable_timeout_seconds,
            )
        except ValueError as exc:
            await self._update(candidate, state="failed", reason=str(exc)[:500])
        except Exception as exc:
            logger.exception("输入候选预检失败: %s", candidate["id"])
            await self._update(candidate, state="failed", reason=str(exc)[:500])
        finally:
            if acquired:
                engine.release_input_preflight(candidate["id"])
            await self._cleanup_stages(candidate["scan_id"], candidate["id"])

    async def _cleanup_stages(self, scan_id, candidate_id=None):
        import re
        import shutil
        for owner, path in await finish_thread(self.repository.stage_paths, scan_id, candidate_id):
            if not re.fullmatch(r"scan_stage_[0-9a-f]{32}", os.path.basename(path)) or os.path.islink(path):
                raise ValueError("扫描临时目录身份不合法，拒绝清理")
            def cleanup():
                def onerror(function, failed_path, exc_info):
                    # 文件被并发移走属于已清理；权限和磁盘异常必须保留。
                    if not isinstance(exc_info[1], FileNotFoundError):
                        raise exc_info[1].with_traceback(exc_info[2])

                shutil.rmtree(path, onerror=onerror)
                if os.path.lexists(path):
                    raise OSError(f"扫描临时目录仍存在，保留清理账本: {path}")
            await finish_thread(cleanup)
            await finish_thread(self.repository.clear_stage, owner, path)

    @staticmethod
    def _has_handoff_capacity(config):
        limit = 2 * max(1, config.processing.max_workers)
        pending = 0
        for task in get_task_engine().get_all_tasks():
            if task.status == TaskStatus.PENDING and task.type == TaskType.AUTO_PROCESS:
                pending += 1
                if pending >= limit:
                    return False
        return True

    async def _update(self, candidate, **changes):
        updated = await finish_thread(
            self.repository.update_candidate, candidate["id"], candidate["version"], **changes,
        )
        if updated:
            candidate["version"] += 1
            for key in ("state", "reason", "evidence"):
                if key in changes:
                    candidate[key] = changes[key]
        return updated

    async def stop(self):
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        workers = list(self._background_runs.values())
        for work in workers:
            work.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        if self._maintenance is not None:
            self._maintenance.cancel()
            await asyncio.gather(self._maintenance, return_exceptions=True)


_input_scan_service = InputScanService()


def get_input_scan_service() -> InputScanService:
    return _input_scan_service
