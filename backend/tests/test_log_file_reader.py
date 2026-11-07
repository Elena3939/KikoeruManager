"""日志字节窗口、轮转和跨块匹配回归。"""
import re
import threading

import pytest

from app.api import routes
from app.core.log_file_reader import forward_records, read_window, reverse_records, rotation_index


def record(index, message="中文 😀 needle", level="INFO", module="worker"):
    return f"2026-11-06 12:00:{index:02d} [{level}] {module} - {message}\n".encode()


@pytest.mark.parametrize("block_size", [7, 31, 64, 4096])
def test_reverse_preserves_unicode_headers_and_multiline_records(tmp_path, block_size):
    path = tmp_path / "app.log"
    rows = [record(1) + 'Traceback:\n  中文续行\nValueError: 😀\n'.encode(), record(2), record(3)]
    path.write_bytes(b"".join(rows))
    actual = list(reverse_records(str(path), block_bytes=block_size))
    assert [row[2] for row in actual] == rows[::-1]
    assert [row[0] for row in actual] == [len(rows[0]) + len(rows[1]), len(rows[0]), 0]
    assert list(forward_records(str(path))) == actual[::-1]


def test_window_counts_records_and_honors_anchor(tmp_path):
    path = tmp_path / "app.log"
    rows = [record(i) + b"  stack line\n" * 3 for i in range(6)]
    path.write_bytes(b"".join(rows))
    anchor = sum(map(len, rows[:3]))
    around = read_window(str(path), anchor, 2, 1, "around")
    assert [row["line"] for row in around] == [row.decode().rstrip() for row in rows[1:5]]
    assert len(routes._tail_lines(str(path), 2)) == 2
    assert read_window(str(path), anchor, 1, 0, "before")[0]["end_offset"] == anchor
    assert read_window(str(path), anchor, 0, 1, "after")[0]["offset"] == anchor


def test_search_filters_continuations_and_utf16_highlights(tmp_path):
    path = tmp_path / "app.log.1"
    rows = [record(1, "[task=12345678] 😀 needle", "ERROR"), record(2, "needle", "ERROR"), record(3, "[task=12345678] needle")]
    path.write_bytes(b"".join(rows))
    snapshot = [{"name": path.name, "path": str(path), "size": path.stat().st_size}]
    result = routes._search_log_snapshots(snapshot, keyword="NEEDLE", levels={"ERROR"}, limit=200,
        total_scan_budget=1, query_signature="test", start_file_index=0, start_offset=path.stat().st_size,
        matched_before=0, cancel_event=threading.Event(), cursor_reset=False,
        module="worker", task_id="12345678", since="2026-11-06T12:00:01", until="2026-11-06T12:00:02")
    assert len(result["results"]) == 1
    item = result["results"][0]
    start, end = item["highlight_ranges"][0]
    assert item["line"].encode("utf-16-le")[start*2:end*2].decode("utf-16-le") == "needle"
    assert path.with_suffix(".1.idx").exists()
    assert rotation_index(str(path))[0][1] == 0


def test_task_search_prefilters_without_building_time_index(tmp_path, monkeypatch):
    path = tmp_path / "app.log.1"
    rows = [record(1, "[task=12345678] first"), record(2, "unrelated"),
            record(3, "task 12345678-abcdef complete")]
    path.write_bytes(b"".join(rows))
    monkeypatch.setattr("app.core.log_file_reader.rotation_index",
                        lambda *args, **kwargs: pytest.fail("未按时间筛选时不应构建索引"))
    snapshot = [{"name": path.name, "path": str(path), "size": path.stat().st_size}]
    result = routes._search_log_snapshots(snapshot, keyword="", levels=set(), limit=200,
        total_scan_budget=1, query_signature="task", start_file_index=0,
        start_offset=path.stat().st_size, matched_before=0, cancel_event=threading.Event(),
        cursor_reset=False, task_id="12345678-abcdef")
    assert result["full_logs"] == [rows[2].decode().rstrip(), rows[0].decode().rstrip()]


def test_stream_reloads_after_generation_change_and_updates_last_record(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(record(1))
    first = routes._read_log_stream_payload(str(path), 2000)
    with path.open("ab") as handle:
        handle.write(b"  traceback continuation\n" + record(2))
    second = routes._read_log_stream_payload(str(path), 2000, first["resume_offset"], first["generation"])
    assert second["is_full"] is False
    assert second["records"][0]["offset"] == 0
    assert "continuation" in second["records"][0]["line"]
    path.rename(tmp_path / "app.log.1")
    path.write_bytes(record(3) * 3)
    third = routes._read_log_stream_payload(str(path), 2000, second["next_offset"], second["generation"])
    assert third["is_full"] is True
    assert len(third["records"]) == 3


def test_byte_match_straddles_block_boundary(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(record(1, "a" * 300 + "中文needle") + record(2))
    rows = list(reverse_records(str(path), block_bytes=11, matcher=re.compile('中文needle'.encode())))
    assert len([row for row in rows if row[2]]) == 1
    assert '中文needle' in rows[-1][2].decode()


def test_stream_rejects_rotation_during_read(tmp_path, monkeypatch):
    from app.core.log_file_reader import LogCursorExpired
    path = tmp_path / 'app.log'
    path.write_bytes(record(1))
    original = routes._read_log_records_window

    def rotate(*args):
        rows = original(*args)
        path.rename(tmp_path / 'app.log.1')
        path.write_bytes(record(2))
        return rows

    monkeypatch.setattr(routes, '_read_log_records_window', rotate)
    with pytest.raises(LogCursorExpired):
        routes._read_log_stream_payload(str(path), 2000)


def test_search_pages_cross_rotations_without_gaps(tmp_path):
    paths = [tmp_path / name for name in ('app.log', 'app.log.1', 'app.log.2')]
    for index, path in enumerate(paths):
        path.write_bytes(b''.join(record(i, f'needle-{index}-{i}') for i in range(6)))
    signature, cursor, found = 'rotations', None, []
    while True:
        snapshots, file_index, offset, matched, reset = routes._build_log_search_snapshots(
            list(map(str, paths)), 1, cursor, signature)
        data = routes._search_log_snapshots(snapshots, keyword='needle', levels=set(), limit=4,
            total_scan_budget=1, query_signature=signature, start_file_index=file_index,
            start_offset=offset, matched_before=matched, cancel_event=threading.Event(), cursor_reset=reset)
        found.extend((item['file'], item['offset']) for item in data['results'])
        if not data['has_more']:
            break
        cursor = routes._decode_log_search_cursor(data['next_cursor'])
    expected = [(path.name, row[0]) for path in paths for row in reverse_records(str(path))]
    assert found == expected


def test_index_time_bounds_keep_records_on_both_sides_of_checkpoint(tmp_path):
    path = tmp_path / 'app.log.1'
    path.write_bytes(b''.join(record(i, 'needle ' + 'a' * 5000) for i in range(50)))
    checkpoints = rotation_index(str(path))
    assert len(checkpoints) > 2
    since, until = checkpoints[1][0], checkpoints[2][0]
    snapshot = [{'name': path.name, 'path': str(path), 'size': path.stat().st_size}]
    data = routes._search_log_snapshots(snapshot, keyword='needle', levels=set(), limit=200,
        total_scan_budget=1, query_signature='time', start_file_index=0,
        start_offset=path.stat().st_size, matched_before=0, cancel_event=threading.Event(),
        cursor_reset=False, since=since, until=until)
    expected = [raw.decode().rstrip() for _, _, raw in reverse_records(str(path)) if since <= raw[:19].decode() <= until]
    assert data['full_logs'] == expected


def test_window_loads_before_across_rotation_files(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    paths = [tmp_path / 'app.log', tmp_path / 'app.log.1']
    paths[0].write_bytes(record(3) + record(4))
    paths[1].write_bytes(record(1) + record(2))
    monkeypatch.setattr('app.core.app_logging.list_log_files', lambda: [SimpleNamespace(name=p.name, path=str(p)) for p in paths])
    monkeypatch.setattr(routes, '_iter_log_files_for_search', lambda: list(map(str, paths)))
    result = asyncio.run(routes.get_logs_window(file='app.log', anchor_offset=0, before=2, after=0, mode='before'))
    assert [item['file'] for item in result['records']] == ['app.log.1'] * 2
    assert result['records'][0]['offset'] == 0


def test_new_search_cancels_previous_in_same_session(tmp_path, monkeypatch):
    import asyncio
    path = tmp_path / 'app.log'
    path.write_bytes(record(1))
    monkeypatch.setattr(routes, '_iter_log_files_for_search', lambda: [str(path)])

    class Request:
        async def is_disconnected(self):
            return False

    async def run():
        started = asyncio.Event()
        cancelled = []

        async def search_io(search):
            # 等待第二个请求注册取消标记后再执行扫描。
            if not started.is_set():
                started.set()
                await asyncio.sleep(.03)
            result = search()
            cancelled.append(result['cancelled'])
            return result

        monkeypatch.setattr(routes, '_run_log_search_io', search_io)
        first = asyncio.create_task(routes.search_logs(Request(), q='needle', session='cancel-test'))
        await started.wait()
        second = asyncio.create_task(routes.search_logs(Request(), q='needle', session='cancel-test'))
        await asyncio.gather(first, second)
        assert sorted(cancelled) == [False, True]
        assert 'cancel-test' not in routes._LOG_SEARCH_SESSIONS

    asyncio.run(run())
