import asyncio

from app.core.library_circle_aggregation_service import (
    LibraryCircleAggregationService,
    _circle_group_path,
    _circle_work_path,
    _encode_circle_key,
)


def _service_with_snapshot(monkeypatch, groups, works_by_group):
    service = LibraryCircleAggregationService()
    snapshot = {
        "groups": groups,
        "groups_by_key": {item["circle_key"]: item for item in groups},
        "works_by_group": works_by_group,
    }
    monkeypatch.setattr(service, "_get_snapshot", lambda force_refresh=False: snapshot)
    return service


def test_circle_browser_keeps_original_folder_name_for_single_work(monkeypatch):
    group_key = _encode_circle_key("circle-a", "Clover Voice")
    service = _service_with_snapshot(
        monkeypatch,
        [{
            "circle_key": group_key,
            "circle_id": "circle-a",
            "circle_name": "Clover Voice",
            "work_count": 1,
            "folder_count": 1,
            "conflict_count": 0,
            "total_size": 12,
            "categories": [],
        }],
        {
            group_key: [{
                "rjcode": "RJ01045951",
                "title": "DLsite 标题不应该覆盖文件夹名",
                "folder_count": 1,
                "total_size": 12,
                "file_count": 1,
                "categories": [],
                "locations": [{
                    "library_id": "local-a",
                    "library_name": "本地 A",
                    "path": "D:/Library/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                    "relative_path": "[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                    "top_category": "",
                    "size": 12,
                    "file_count": 1,
                    "modified_time": 1000,
                    "name": "[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                }],
                "primary_category": "",
                "primary_path": "D:/Library/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                "primary_library_id": "local-a",
                "conflict": False,
            }],
        },
    )

    payload = asyncio.run(service.browse_circle_path(current_path=_circle_group_path(group_key)))

    assert payload["files"][0]["circle_row_type"] == "work-single"
    assert payload["files"][0]["name"] == "[Clover VoiceJRJ01045951] (CV 実羽ゆうき)"
    assert payload["files"][0]["circle_title"] == "DLsite 标题不应该覆盖文件夹名"
    assert payload["files"][0]["circle_real_library_id"] == "local-a"


def test_circle_browser_only_expands_locations_for_conflict_work(monkeypatch):
    group_key = _encode_circle_key("circle-a", "Clover Voice")
    work = {
        "rjcode": "RJ01045951",
        "title": "",
        "folder_count": 2,
        "total_size": 20,
        "file_count": 2,
        "categories": [],
        "locations": [
            {
                "library_id": "local-a",
                "library_name": "本地 A",
                "path": "D:/Library/A/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                "relative_path": "A/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                "top_category": "A",
                "size": 10,
                "file_count": 1,
                "modified_time": 1000,
                "name": "[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
            },
            {
                "library_id": "local-a",
                "library_name": "本地 A",
                "path": "D:/Library/B/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                "relative_path": "B/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
                "top_category": "B",
                "size": 10,
                "file_count": 1,
                "modified_time": 1000,
                "name": "[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
            },
        ],
        "primary_category": "A",
        "primary_path": "D:/Library/A/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
        "primary_library_id": "local-a",
        "conflict": True,
    }
    service = _service_with_snapshot(
        monkeypatch,
        [{
            "circle_key": group_key,
            "circle_id": "circle-a",
            "circle_name": "Clover Voice",
            "work_count": 1,
            "folder_count": 2,
            "conflict_count": 1,
            "total_size": 20,
            "categories": ["A", "B"],
        }],
        {group_key: [work]},
    )

    group_payload = asyncio.run(service.browse_circle_path(current_path=_circle_group_path(group_key)))
    conflict_payload = asyncio.run(service.browse_circle_path(current_path=_circle_work_path(group_key, "RJ01045951")))

    assert group_payload["files"][0]["circle_row_type"] == "work-conflict"
    assert group_payload["files"][0]["name"] == "RJ01045951 · 2 个路径冲突"
    assert [item["circle_row_type"] for item in conflict_payload["files"]] == ["conflict-location", "conflict-location"]
    assert [item["circle_relative_path"] for item in conflict_payload["files"]] == [
        "A/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
        "B/[Clover VoiceJRJ01045951] (CV 実羽ゆうき)",
    ]


def test_circle_browser_root_does_not_build_every_group_work(monkeypatch):
    group_key = _encode_circle_key("circle-a", "Clover Voice")
    service = _service_with_snapshot(
        monkeypatch,
        [{
            "circle_key": group_key,
            "circle_id": "circle-a",
            "circle_name": "Clover Voice",
            "work_count": 1,
            "folder_count": 1,
            "conflict_count": 0,
            "total_size": 12,
            "modified_time": 3000,
            "categories": [],
            "rjcodes": ["RJ01045951"],
        }],
        {},
    )

    def fail_build_work_items(_rows):
        raise AssertionError("根列表不应该构建所有社团作品明细")

    monkeypatch.setattr(service, "_build_work_items", fail_build_work_items)

    payload = asyncio.run(service.browse_circle_path(current_path="circle:/"))

    assert payload["files"][0]["circle_row_type"] == "group"
    assert payload["files"][0]["name"] == "Clover Voice"
    assert payload["files"][0]["modified_time"] == 3000
