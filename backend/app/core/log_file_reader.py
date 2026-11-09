"""日志文件的字节寻址；所有 offset 都是原始 UTF-8 文件的字节位置。"""
from __future__ import annotations

import os
import re
import json
import time
import bisect
from typing import Iterator


HEADER = re.compile(
    rb"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?\s+(?:\[\w+\]|-\s+\S+\s+-\s+\w+\s+-)",
    re.MULTILINE,
)
BLOCK_BYTES = 1024 * 1024


class LogCursorExpired(OSError):
    """文件在定位与读取之间发生轮转或截断。"""


def validate_snapshot(snapshot, stat):
    if ((snapshot.get("inode") and snapshot["inode"] != stat.st_ino)
            or stat.st_size < snapshot["size"]
            or (snapshot["name"] != "app.log" and stat.st_size != snapshot["size"])):
        raise LogCursorExpired("日志文件已轮转")


def reverse_records(path: str, end_offset: int | None = None, block_bytes: int = BLOCK_BYTES, matcher=None, snapshot=None) -> Iterator[tuple[int, int, bytes]]:
    """从尾到头读取完整记录；跨块的 UTF-8、头行和 traceback 全部保留。"""
    with open(path, "rb") as handle:
        if snapshot:
            validate_snapshot(snapshot, os.fstat(handle.fileno()))
        handle.seek(0, os.SEEK_END)
        end = handle.tell() if end_offset is None else min(handle.tell(), max(0, end_offset))
        position = end
        pending = b""
        while position:
            size = min(block_bytes, position)
            position -= size
            handle.seek(position)
            data = handle.read(size) + pending
            # 在整块 bytes 上匹配一次，未命中的记录只返回边界供预算与游标推进。
            hits = [match.start() for match in matcher.finditer(data)] if matcher else None
            starts = [match.start() for match in HEADER.finditer(data) if position == 0 or match.start() > 0]
            boundary = len(data)
            for start in reversed(starts):
                hit_index = bisect.bisect_left(hits, start) if hits is not None else 0
                matched = hits is None or (hit_index < len(hits) and hits[hit_index] < boundary)
                raw = data[start:boundary] if matched else b""
                if not matched or raw.strip():
                    yield position + start, position + boundary, raw
                boundary = start
            pending = data[:boundary]
        if pending.strip():
            yield 0, len(pending), pending if matcher is None or matcher.search(pending) else b""


def forward_records(path: str, start: int = 0) -> Iterator[tuple[int, int, bytes]]:
    with open(path, "rb") as handle:
        handle.seek(max(0, start))
        record_start = handle.tell()
        parts: list[bytes] = []
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                if parts:
                    yield record_start, offset, b"".join(parts)
                return
            if HEADER.match(raw) and parts:
                yield record_start, offset, b"".join(parts)
                record_start, parts = offset, []
            parts.append(raw)


def record_dict(path: str, row: tuple[int, int, bytes]) -> dict:
    offset, end_offset, raw = row
    return {
        "file": os.path.basename(path), "offset": offset, "end_offset": end_offset,
        "line": raw.decode("utf-8", errors="replace").rstrip("\r\n"),
    }


def read_window(path: str, anchor_offset: int, before: int, after: int, mode: str) -> list[dict]:
    anchor = max(0, min(int(anchor_offset), os.path.getsize(path)))
    before, after = max(0, before), max(0, after)
    size = os.path.getsize(path)
    # 首屏尾部读取本来就是 anchor=size，此时无需先反向扫描一次定位
    # 最近记录；直接进入 before 分支，避免对同一段日志做重复读取。
    start = 0
    if not (mode == "before" and anchor == size):
        for row in reverse_records(path, min(size, anchor + 256), BLOCK_BYTES):
            if row[0] <= anchor:
                start = row[0]
                break
    if mode == "before":
        boundary = anchor if anchor == size else start
        rows = []
        if before:
            for row in reverse_records(path, boundary, BLOCK_BYTES):
                rows.append(record_dict(path, row))
                if len(rows) >= before:
                    break
        return list(reversed(rows))
    preceding = read_window(path, start, before, 0, "before") if mode == "around" else []
    following = []
    count = after + (1 if mode == "around" else 0)
    if count:
        for row in forward_records(path, start):
            if mode == "after" and row[1] <= anchor:
                continue
            following.append(record_dict(path, row))
            if len(following) >= count:
                break
    return preceding + following


def rotation_index(path: str, *, deadline=None, cancel_event=None) -> list[list]:
    """轮转文件按 64KB 保留时间/偏移检查点；写临时文件后原子替换。"""
    if not re.search(r"app\.log\.\d+$", path):
        return []
    stat = os.stat(path)
    generation = [stat.st_ino, stat.st_size, stat.st_mtime_ns]
    index_path = path + ".idx"
    try:
        with open(index_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("generation") == generation:
            return payload["checkpoints"]
    except (OSError, ValueError, KeyError):
        pass
    checkpoints = []
    next_block = 0
    with open(path, "rb") as handle:
        position, overlap = 0, b""
        while True:
            if (deadline is not None and time.monotonic() >= deadline) or (cancel_event and cancel_event.is_set()):
                # 未完整扫描的索引不能发布；本页继续直接扫描，游标仍可向前推进。
                return []
            chunk = handle.read(BLOCK_BYTES)
            if not chunk:
                break
            data = overlap + chunk
            base = position - len(overlap)
            for match in HEADER.finditer(data):
                if base and match.start() == 0:
                    continue
                start = base + match.start()
                if start >= next_block:
                    checkpoints.append([data[match.start():match.start() + 19].decode("ascii"), start])
                    next_block = start + 64 * 1024
            position += len(chunk)
            overlap = data[-4096:]
    payload = {"generation": generation, "checkpoints": checkpoints}
    temporary = f"{index_path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(temporary, index_path)
    except OSError:
        pass
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    return checkpoints


def _search_snapshots(snapshots, *, keyword, levels, limit, query_signature,
                     start_file_index, start_offset, matched_before, cancel_event,
                     cursor_reset, encode_cursor, module="", task_id="", since="", until="", **_):
    deadline = time.monotonic() + 0.25
    # 任务条件只用于字节块预筛选，最终仍在日志头中验证完整语义。
    matcher = (re.compile(re.escape(keyword.encode("utf-8")), re.IGNORECASE) if keyword
               else re.compile(re.escape(task_id[:8].encode("utf-8"))) if task_id else None)
    modules = [value.strip() for value in module.split(',') if value.strip()]
    module_matcher = re.compile(r"(?:\]\s+| - )(?:" + '|'.join(re.escape(value) for value in modules) + r")\s+-\s+") if modules else None
    since = since.replace('T', ' ')
    until = until.replace('T', ' ')
    if len(since) == 16:
        since += ':00'
    if len(until) == 16:
        until += ':59'
    results, scanned = [], []
    scan_bytes = 0
    next_file, next_offset = start_file_index, start_offset
    stopped, cancelled = False, False
    for file_index in range(start_file_index, len(snapshots)):
        snapshot = snapshots[file_index]
        file_end = start_offset if file_index == start_file_index else snapshot["size"]
        checkpoints = (rotation_index(snapshot["path"], deadline=min(deadline, time.monotonic() + 0.15), cancel_event=cancel_event)
                       if since or until else [])
        floor = 0
        if checkpoints and since:
            times = [item[0] for item in checkpoints]
            floor = checkpoints[max(0, bisect.bisect_left(times, since[:19]) - 1)][1]
        if checkpoints and until:
            times = [item[0] for item in checkpoints]
            right = bisect.bisect_right(times, until[:19])
            if right < len(checkpoints):
                file_end = min(file_end, checkpoints[right][1])
        file_bytes = 0
        for offset, end, raw in reverse_records(snapshot["path"], file_end, matcher=matcher, snapshot=snapshot):
            if cancel_event.is_set():
                cancelled = True
                break
            if offset < floor:
                break
            if len(results) >= limit or time.monotonic() >= deadline:
                # 当前记录尚未检查，下一页从它的右边界继续，不能跳过本条。
                next_file, next_offset, stopped = file_index, end, True
                break
            next_file, next_offset = file_index, offset
            file_bytes += end - offset
            scan_bytes += end - offset
            if not raw:
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            head = text.split("\n", 1)[0]
            level = re.search(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]| - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - ", head)
            if levels and (not level or (level.group(1) or level.group(2)) not in levels):
                continue
            if module_matcher and not module_matcher.search(head):
                continue
            if task_id and f"[task={task_id[:8]}]" not in head and task_id not in head:
                continue
            timestamp = head[:19].replace("T", " ")
            if since and timestamp < since[:19].replace("T", " "):
                continue
            if until and timestamp > until[:19].replace("T", " "):
                continue
            # 前端 String.slice 使用 UTF-16 下标。
            ranges = [[len(text[:hit.start()].encode('utf-16-le')) // 2, len(text[:hit.end()].encode('utf-16-le')) // 2]
                      for hit in re.finditer(re.escape(keyword), text, re.IGNORECASE)] if keyword else []
            results.append({"file": snapshot["name"], "offset": offset, "end_offset": end,
                            "line": text, "highlight_ranges": ranges})
        scanned.append({"name": snapshot["name"], "bytes": file_bytes, "total_bytes": snapshot["size"]})
        validate_snapshot(snapshot, os.stat(snapshot["path"]))
        if stopped or cancelled:
            break
        next_file = file_index + 1
        next_offset = snapshots[next_file]["size"] if next_file < len(snapshots) else 0
    has_more = not cancelled and next_file < len(snapshots) and (next_offset > 0 or stopped)
    matched_after = matched_before + len(results)
    cursor = encode_cursor(snapshots, query_signature, next_file, next_offset, matched_after) if has_more else ""
    # 旧调用仍使用有界预览；字节定位结果和 full_logs 保留完整记录。
    previews = []
    for item in results:
        line = item["line"]
        if len(line) > 16 * 1024:
            hit = re.search(re.escape(keyword), line, re.IGNORECASE) if keyword else None
            start = max(0, (hit.start() if hit else 0) - 128)
            line = line[start:start + 16 * 1024] + "…"
        previews.append(line)
    return {"logs": previews, "full_logs": [item["line"] for item in results],
            "results": results, "total_matched": matched_after + int(has_more),
            "matched_before": matched_before, "matched_after": matched_after,
            "next_cursor": cursor, "has_more": has_more, "total_is_estimate": has_more,
            "scan_bytes": scan_bytes, "scanned_files": scanned, "stopped_early": stopped,
            "cursor_reset": cursor_reset, "cursor_expired": cursor_reset, "cancelled": cancelled}


def search_snapshots(snapshots, **kwargs):
    try:
        return _search_snapshots(snapshots, **kwargs)
    except (FileNotFoundError, LogCursorExpired):
        # 绝不能把轮转后同名文件的新字节冒充旧游标的命中结果。
        return {"logs": [], "full_logs": [], "results": [], "next_cursor": "",
                "has_more": False, "total_matched": 0, "scan_bytes": 0,
                "scanned_files": [], "cursor_reset": True, "cursor_expired": True,
                "cancelled": False, "stopped_early": False}
