import threading

from app.api import routes


def _snapshots(path, *, scan_bytes=1024 * 1024, cursor="", keyword="needle"):
    signature = routes._log_search_query_signature(keyword, set(), scan_bytes, True)
    payload = routes._decode_log_search_cursor(cursor)
    snapshots, file_index, offset, matched_before, cursor_reset = routes._build_log_search_snapshots(
        [str(path)],
        scan_bytes,
        payload,
        signature,
    )
    return signature, snapshots, file_index, offset, matched_before, cursor_reset


def _search(path, *, cursor="", keyword="needle", limit=5, scan_budget=1024 * 1024, cancel_event=None):
    signature, snapshots, file_index, offset, matched_before, cursor_reset = _snapshots(
        path,
        cursor=cursor,
        keyword=keyword,
    )
    return routes._search_log_snapshots(
        snapshots,
        keyword=keyword,
        levels=set(),
        limit=limit,
        total_scan_budget=scan_budget,
        query_signature=signature,
        start_file_index=file_index,
        start_offset=offset,
        matched_before=matched_before,
        cancel_event=cancel_event or threading.Event(),
        cursor_reset=cursor_reset,
    )


def test_log_search_cursor_continues_without_rescanning_matches(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text(
        "".join(f"2026-07-12 10:00:{index:02d} [INFO] test - needle-{index}\n" for index in range(13)),
        encoding="utf-8",
    )

    first = _search(log_file)
    second = _search(log_file, cursor=first["next_cursor"])
    third = _search(log_file, cursor=second["next_cursor"])

    assert [len(first["logs"]), len(second["logs"]), len(third["logs"])] == [5, 5, 3]
    assert first["matched_before"] == 0
    assert second["matched_before"] == 5
    assert third["matched_before"] == 10
    assert "needle-4" in first["logs"][-1]
    assert "needle-5" in second["logs"][0]
    assert "needle-12" in third["logs"][-1]
    assert third["has_more"] is False


def test_log_search_matches_keyword_across_large_fragment_boundary(tmp_path):
    log_file = tmp_path / "app.log"
    prefix = b"2026-07-12 10:00:00 [INFO] test - "
    padding = b"a" * (routes._LOG_SEARCH_RAW_FRAGMENT_BYTES - len(prefix) - 3)
    log_file.write_bytes(prefix + padding + b"nee" + b"dle-tail")

    result = _search(log_file, limit=5)

    assert len(result["logs"]) == 1
    assert "needle" in result["logs"][0]
    assert len(result["logs"][0]) <= routes._LOG_LINE_LENGTH_CAP + 1
    assert result["full_logs"] == [
        (prefix + padding + b"nee" + b"dle-tail").decode("utf-8")
    ]
    assert len(result["full_logs"][0]) > routes._LOG_LINE_LENGTH_CAP


def test_log_search_stops_when_cancelled(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("needle\n" * 100, encoding="utf-8")
    cancel_event = threading.Event()
    cancel_event.set()

    result = _search(log_file, cancel_event=cancel_event)

    assert result["cancelled"] is True
    assert result["logs"] == []
    assert result["scan_bytes"] == 0


def test_log_search_resets_cursor_after_file_truncate(tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text("needle\n" * 20, encoding="utf-8")
    first = _search(log_file)
    log_file.write_text("needle-new\n", encoding="utf-8")

    second = _search(log_file, cursor=first["next_cursor"])

    assert second["cursor_reset"] is True
    assert second["matched_before"] == 0
    assert second["logs"] == ["needle-new"]
