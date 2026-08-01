"""Phase 4B：activity_log_aggregator.merge_activity_rows 快照回归测试。

目的：在把 1877 行合并算法按 domain 拆子模块之前，先用一组 JSON fixture 把
当前行为钉死，确保后续拆分/重构任一步骤都不会静默改变对外 items 结构。

工作方式：
- fixture 目录：tests/fixtures/activity_log_aggregator/
- 每个 scenario 两文件：<name>.input.json / <name>.expected.json
- 普通跑：加载输入 → 调 merge_activity_rows → 对比 expected
- 首次创建 scenario 或重新校准基准：设 env UPDATE_SNAPSHOTS=1，测试会把当前
  输出写回 .expected.json 并 xfail（强制人工 review 再去掉 env 变量）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "activity_log_aggregator"


class _FakeActivityLog:
    """
    merge_activity_rows 只需要一个带 ``to_dict()`` 方法的对象。
    这里不引入 ORM / DB，直接拿 fixture 里的 dict 还原。
    """

    __slots__ = ("_payload",)

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> Dict[str, Any]:
        # 返回深拷贝，避免 aggregator 内部原地改动污染 fixture
        return json.loads(json.dumps(self._payload))


def _discover_scenarios() -> List[str]:
    if not FIXTURES_DIR.exists():
        return []
    names = sorted(
        p.stem.removesuffix(".input") if p.stem.endswith(".input") else p.stem
        for p in FIXTURES_DIR.glob("*.input.json")
    )
    # 保险：去重并按名称排序
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _load_input(name: str) -> List[Dict[str, Any]]:
    with (FIXTURES_DIR / f"{name}.input.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_expected(name: str) -> Any:
    path = FIXTURES_DIR / f"{name}.expected.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_expected(name: str, data: Any) -> None:
    path = FIXTURES_DIR / f"{name}.expected.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def _run_aggregator(rows: List[Dict[str, Any]]) -> Any:
    from app.core.activity_log_aggregator import merge_activity_rows

    fake_rows = [_FakeActivityLog(row) for row in rows]
    return merge_activity_rows(fake_rows)


SCENARIOS = _discover_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_merge_activity_rows_snapshot(scenario: str) -> None:
    """对每个 fixture scenario 跑一次合并，和 expected 精确比对。"""
    update_mode = os.environ.get("UPDATE_SNAPSHOTS") == "1"

    rows = _load_input(scenario)
    actual = _run_aggregator(rows)

    # 序列化走和写入基准相同的规范（ensure_ascii=False、sort_keys=True），
    # 这样对比出来的 diff 和后续人工维护 .expected.json 的 diff 是一致的。
    serialized = json.loads(json.dumps(actual, ensure_ascii=False, sort_keys=True))

    if update_mode:
        _write_expected(scenario, serialized)
        pytest.xfail(
            f"[UPDATE_SNAPSHOTS] 已重写 {scenario}.expected.json；去掉 env 变量后重跑以固化基准"
        )

    expected = _load_expected(scenario)
    if expected is None:
        pytest.skip(
            f"{scenario}.expected.json 不存在。用 UPDATE_SNAPSHOTS=1 pytest ... 生成基准"
        )
    assert serialized == expected, (
        f"scenario={scenario} 快照不匹配。\n"
        f"如果是算法有意变更，请用 UPDATE_SNAPSHOTS=1 刷新基准，并人工审核 diff。"
    )


def test_fixtures_present() -> None:
    """防御：确保 fixture 目录存在且至少有一个 scenario，避免测试全 skip 却误以为通过。"""
    assert FIXTURES_DIR.exists(), f"fixture 目录不存在：{FIXTURES_DIR}"
    assert SCENARIOS, f"fixture 目录没有 *.input.json：{FIXTURES_DIR}"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_from_dicts_does_not_mutate_input(scenario: str) -> None:
    """Phase 4D 防御：row-dict 缓存场景下 from_dicts 会被多个请求传同一组 dict。
    合并算法如果在内部原地改写了入参 dict，缓存就会被污染，第二次调用结果就变形了。

    本测试保证：
    1) 调用 from_dicts 前后，入参 rows 的字节序列化完全一致（没有被原地 mutate）
    2) 两次连续调用给出一致的输出（幂等）
    """
    from app.core.activity_log_aggregator import merge_activity_rows_from_dicts

    rows = _load_input(scenario)
    snapshot_before = json.dumps(rows, ensure_ascii=False, sort_keys=True)

    first = merge_activity_rows_from_dicts(rows)
    snapshot_after_first = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    assert snapshot_before == snapshot_after_first, (
        f"scenario={scenario} merge_activity_rows_from_dicts 原地改写了入参，"
        "会污染行级缓存。需要把入参视为不可变，在 aggregator 内自己 deepcopy 再合并。"
    )

    second = merge_activity_rows_from_dicts(rows)
    assert (
        json.loads(json.dumps(first, ensure_ascii=False, sort_keys=True))
        == json.loads(json.dumps(second, ensure_ascii=False, sort_keys=True))
    ), f"scenario={scenario} from_dicts 不幂等，同一输入两次输出不一致"


def test_multi_rj_extract_subtasks_roll_up_filtered_size_to_parent() -> None:
    from app.core.activity_log_aggregator import merge_activity_rows_from_dicts

    rows = [
        {
            "id": "parent",
            "category": "auto_import",
            "action": "task_finished",
            "status": "success",
            "summary": "解压入库完成，压缩包 66.79 GB，解压产物 120.00 GB，耗时 1 分 0 秒",
            "task_id": "parent-task",
            "source_path": "/archives/big.zip",
            "rjcode": "RJ00000001",
            "created_at": "2026-05-25T15:13:41",
            "detail": {
                "batch_id": "parent-task",
                "archive_size_bytes": 1024,
                "extract_output_bytes": 4096,
                "duration_ms": 60000,
                "multi_rj_subtask_count": 2,
            },
        },
        {
            "id": "child-1",
            "category": "process_existing",
            "action": "task_finished",
            "status": "success",
            "summary": "完成",
            "task_id": "child-task-1",
            "source_path": "/temp/RJ00000011",
            "rjcode": "RJ00000011",
            "created_at": "2026-05-25T15:14:41",
            "detail": {
                "batch_id": "parent-task",
                "parent_task_id": "parent-task",
                "source_action": "multi_rj_extract_subtask",
                "filtered_count": 2,
                "filtered_size": 300,
            },
        },
        {
            "id": "child-2",
            "category": "process_existing",
            "action": "task_finished",
            "status": "success",
            "summary": "完成",
            "task_id": "child-task-2",
            "source_path": "/temp/RJ00000012",
            "rjcode": "RJ00000012",
            "created_at": "2026-05-25T15:15:41",
            "detail": {
                "batch_id": "parent-task",
                "parent_task_id": "parent-task",
                "source_action": "multi_rj_extract_subtask",
                "filtered_count": 1,
                "filtered_size": 700,
            },
        },
    ]

    result = merge_activity_rows_from_dicts(rows)

    assert len(result) == 1
    detail = result[0]["detail"]
    assert detail["child_row_count"] == 2
    assert detail["aggregate_filtered_count"] == 3
    assert detail["aggregate_filtered_size"] == 1000
