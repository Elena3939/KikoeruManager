"""从下载运行态快照生成工作台和后台小窗共用的统计。"""

import math
from datetime import datetime, timedelta, timezone


def _number(value):
    try:
        result = float(value)
        return max(0, result) if math.isfinite(result) else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def select_download_batch(tasks, batch_task_ids=(), batch_started_at=""):
    """追加任务时排除提交前已结束的旧任务，保留未完成任务及本轮完成项。"""
    def timestamp(value):
        try:
            return datetime.fromisoformat(str(value)).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    batch_ids = set(batch_task_ids)
    boundary = timestamp(batch_started_at)
    if boundary is None:
        created = [
            timestamp(task.get("created_at"))
            for task in tasks if str(task.get("id")) in batch_ids
        ]
        created = [value for value in created if value is not None]
        boundary = min(created) if created else None
    if boundary is None:
        return tasks, batch_started_at

    selected = []
    for task in tasks:
        status = str(task.get("display_status") or task.get("status") or "").lower()
        if str(task.get("id")) not in batch_ids and status in {
            "completed", "success", "succeeded", "cancelled", "canceled",
        }:
            finished = timestamp(task.get("completed_at"))
            if finished is None or finished < boundary:
                continue
        selected.append(task)
    return selected, datetime.fromtimestamp(boundary, timezone.utc).isoformat()


def summarize_download_tasks(tasks):
    total = transferred = speed = remaining = 0
    fractions = []
    known_sizes = True
    eta_known = True
    completed = bool(tasks)
    statuses = set()
    for task in tasks:
        status = str(task.get("display_status") or task.get("status") or "")
        statuses.add(status)
        runtime = (
            task.get("download_runtime")
            or (task.get("performance_metrics") or {}).get("download_runtime")
            or ((task.get("task_metadata") or {}).get("performance_metrics") or {}).get("download_runtime")
            or {}
        )
        files = task.get("download_files") or []
        size = _number(runtime.get("total_bytes")) or sum(
            _number(row.get("size_bytes") or row.get("size") or row.get("total")) for row in files
        )
        done = status == "completed"
        downloaded = size if done else _number(
            runtime.get("transferred_bytes") if runtime.get("transferred_bytes") is not None else sum(
                _number(row.get("size_bytes") or row.get("size") or row.get("total"))
                if row.get("status") == "completed" else _number(row.get("downloaded"))
                for row in files
            )
        )
        downloaded = min(size, downloaded) if size else 0
        fraction = 1 if done else min(1, downloaded / size if size else _number(task.get("progress")) / 100)
        fractions.append(fraction)
        completed = completed and done
        known_sizes = known_sizes and size > 0
        total += size
        transferred += downloaded
        if status not in {"completed", "cancelled", "canceled"}:
            remaining += max(0, size - downloaded)
            eta_known = eta_known and size > 0
        if task.get("status") == "processing" and _number(runtime.get("active_file_count")) > 0:
            speed += _number(runtime.get("speed_bytes_per_sec"))
    fraction = transferred / total if total and known_sizes else sum(fractions) / max(1, len(fractions))
    blocked = bool(statuses & {"paused", "failed", "partial_failed", "waiting_manual"})
    eta = math.ceil(remaining / speed) if speed > 0 and remaining > 0 and eta_known and not blocked else None
    now = datetime.now(timezone.utc)
    # 极低速度产生的异常大 ETA 不应让状态接口溢出。
    if eta is not None and eta > (datetime.max.replace(tzinfo=timezone.utc) - now).total_seconds() - 1:
        eta = None
    eta_status = (
        "completed" if completed else
        "needs_attention" if statuses & {"failed", "partial_failed", "waiting_manual"} else
        "paused" if "paused" in statuses else
        "cancelled" if statuses and statuses <= {"cancelled", "canceled", "completed"} else
        "downloading" if eta is not None else
        "calculating"
    )
    return {
        "task_ids": [str(task["id"]) for task in tasks],
        "progress_percent": 100 if completed else min(99, math.floor(fraction * 100)),
        "total_bytes": int(total),
        "transferred_bytes": int(transferred),
        "remaining_bytes": int(remaining),
        "speed_bytes_per_sec": speed,
        "eta_seconds": eta,
        "eta_status": eta_status,
        "estimated_completion_at": (now + timedelta(seconds=eta)).isoformat() if eta is not None else None,
        "sampled_at": now.isoformat(),
    }
