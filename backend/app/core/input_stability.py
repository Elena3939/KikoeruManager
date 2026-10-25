"""扫描与解压共用的轻量源身份采样，不在采样函数中等待。"""

import os
import time


class InputSourceNotReady(Exception):
    """源需要到期复查；任务引擎应释放执行许可后重新排队。"""


def sample_sources(paths):
    result = {}
    for path in sorted(set(paths)):
        if os.path.exists(path + ".aria2"):
            return None, "aria2_present"
        stat = os.stat(path)
        with open(path, "rb") as source:
            source.read(1)
        result[path] = {
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "dev": stat.st_dev, "ino": stat.st_ino,
        }
    return result, None


def observe_sources(paths, previous, *, checks, interval, needs_stability=True, now=None):
    now = time.time() if now is None else now
    fingerprints, reason = sample_sources(paths)
    policy = {"checks": checks, "interval": interval}
    evidence = {
        "needs_stability": needs_stability, "policy": policy,
        "fingerprints": fingerprints or {}, "observed_at": now,
        "consistent_checks": 0, "verified": False,
    }
    if reason:
        return evidence, reason
    if previous.get("fingerprints") == fingerprints and previous.get("policy") == policy:
        elapsed = now - float(previous.get("observed_at") or 0)
        if 0 <= elapsed < interval:
            return dict(previous), None if previous.get("verified") else "file_changing"
        if elapsed >= interval:
            evidence["consistent_checks"] = int(previous.get("consistent_checks") or 0) + 1
    evidence["verified"] = not needs_stability or evidence["consistent_checks"] >= checks
    return evidence, None if evidence["verified"] else "file_changing"


def valid_stability_evidence(evidence, paths, *, checks, interval, max_age=15, now=None):
    """旧策略、过期、缺少任一成员或被替换的文件均必须重新观察。"""
    now = time.time() if now is None else now
    if not evidence.get("verified") or not evidence.get("needs_stability"):
        return False
    age = now - float(evidence.get("observed_at") or 0)
    if age < 0 or age > max_age:
        return False
    if evidence.get("policy") != {"checks": checks, "interval": interval}:
        return False
    try:
        fingerprints, reason = sample_sources(paths)
    except OSError:
        return False
    return not reason and fingerprints == evidence.get("fingerprints")


def check_task_sources(task, config, *, paths=None, max_wait=1800, now=None):
    """执行前只采样一次；到期时间随任务快照保存，不创建睡眠任务。"""
    now = time.time() if now is None else now
    metadata = task.task_metadata
    paths = list(paths or metadata.get("input_members") or [task.source_path])
    checks = max(1, config.processing.file_stable_checks)
    interval = max(0.1, config.processing.file_stable_interval)
    evidence = metadata.get("input_stability") or {}
    if valid_stability_evidence(evidence, paths, checks=checks, interval=interval, now=now):
        metadata.pop("input_source_wait", None)
        return None
    wait = metadata.get("input_source_wait") or {"started_at": now}
    if now - wait["started_at"] >= max_wait:
        raise TimeoutError(f"等待文件稳定或可读超时 ({max_wait}秒): {task.source_path}")
    # 手扫单包没有观察窗口，过期证据也必须重新观察。
    if not evidence.get("needs_stability") or now - evidence.get("observed_at", 0) > 15:
        evidence = {}
    try:
        evidence, reason = observe_sources(
            paths, evidence, checks=checks, interval=interval, now=now,
        )
    except OSError:
        evidence, reason = {}, "source_unreadable"
    metadata["input_stability"] = evidence
    metadata["input_members"] = paths
    if reason:
        metadata["input_source_wait"] = {
            **wait, "reason": reason, "next_check_at": now + interval,
        }
    else:
        metadata.pop("input_source_wait", None)
    return reason
