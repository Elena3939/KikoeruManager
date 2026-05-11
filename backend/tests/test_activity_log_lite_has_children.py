"""
单元测试：`_has_potential_children` 的判定边界。

重点保证以下场景：
 - 邮件监听一轮里 N 条单 RJ 触发索引行（兄弟而不是子任务）→ False
 - 邮件监听同一轮的 fetch_check 总结行 → True
 - 批量启动摘要（解压入库 / 字幕抓取）→ True
 - aggregator 后处理过的 child_row_count 行 → True
 - 只有 batch_id / session_id / session_key 横向分组键的孤立行 → False
"""
from app.core.activity_log_lite import _has_potential_children


# === 场景 1：邮件监听一轮里 N 条「单 RJ 触发索引」（兄弟而不是子任务） ===
def test_email_single_index_trigger_is_not_parent():
    """这是用户截图里被错标"有子任务"的真实场景：
    detail 里只有 batch_id（横向分组键），没有任何子计数 / 子列表 / batch_ action /
    _batch mode 信号。修复后应返回 False。
    """
    detail = {
        "mode": "email_new_release_item",
        "batch_id": "email-watch-bb5aef2c4f6f48e5b13bb81e704f9cf3",
        "circle_name": "あぶそりゅ〜と",
        "rjcode": "RJ01615543",
        "only_new_works": True,
    }
    assert _has_potential_children(detail, "circle_index_triggered") is False


# === 场景 2：邮件监听一轮的 fetch_check 总结行 ===
def test_email_fetch_check_summary_is_parent():
    """同一轮的总结行：mode 以 _batch 结尾、有 triggered 计数、rjcodes 列表，
    任何一个信号都应让它命中。"""
    detail = {
        "mode": "email_new_release_batch",
        "batch_id": "email-watch-bb5aef2c4f6f48e5b13bb81e704f9cf3",
        "unseen_total": 39,
        "triggered": 1,
        "rjcodes": ["RJ01615543"],
        "items": [{"rjcode": "RJ01615543", "circle_name": "あぶそりゅ〜と"}],
    }
    assert _has_potential_children(detail, "fetch_check") is True


# === 场景 3：批量启动摘要（created_count > 0） ===
def test_batch_start_with_created_count_is_parent():
    detail = {
        "mode": "import_batch_start",
        "batch_id": "abc",
        "requested_count": 10,
        "created_count": 7,
    }
    assert _has_potential_children(detail, "batch_start") is True


# === 场景 4：aggregator 后处理注入的 child_row_count ===
def test_aggregator_child_row_count_is_parent():
    detail = {
        "child_row_count": 5,
        "child_rows": [{"id": "x"}, {"id": "y"}],
    }
    assert _has_potential_children(detail, "any") is True


# === 场景 5：字幕配对 paired / unpaired_child_count ===
def test_subtitle_pair_counts_is_parent():
    assert _has_potential_children({"paired_child_count": 3}, "pair_summary") is True
    assert _has_potential_children({"unpaired_child_count": 1}, "pair_summary") is True


# === 场景 6：action 以 batch_ 开头无论 detail 如何都判 True ===
def test_batch_action_prefix_is_parent():
    assert _has_potential_children({}, "batch_api_rename") is True
    assert _has_potential_children({"unrelated": 1}, "batch_manual_rename") is True


# === 场景 7：只有 batch_id 没有任何显式信号 → False（修复点） ===
def test_only_batch_id_is_not_parent():
    """关键回归点：旧版会因为 batch_id 存在就返回 True，导致每条 batch 成员
    都被错标。"""
    assert _has_potential_children({"batch_id": "abc"}, "trigger_index") is False


def test_only_session_key_is_not_parent():
    assert _has_potential_children({"session_key": "xyz"}, "asmr_sync_step") is False


def test_only_session_id_is_not_parent():
    assert _has_potential_children({"session_id": "abc"}, "circle_step") is False


# === 场景 8：空字典 / 非字典 → False ===
def test_empty_detail_is_not_parent():
    assert _has_potential_children({}, "") is False
    assert _has_potential_children({}, "circle_index_triggered") is False


def test_non_dict_detail_is_not_parent():
    assert _has_potential_children(None, "") is False  # type: ignore[arg-type]
    assert _has_potential_children("not a dict", "") is False  # type: ignore[arg-type]
    assert _has_potential_children([], "") is False  # type: ignore[arg-type]


# === 场景 9：计数为 0 / 字符串数字 ===
def test_zero_count_does_not_trigger():
    """triggered=0 不能算有子任务，避免空批次也被错标。"""
    assert _has_potential_children({"triggered": 0}, "fetch_check") is False
    assert _has_potential_children({"created_count": 0}, "batch_start") is True  # batch_ 前缀仍命中


def test_string_count_parses():
    """detail 字段有时会被序列化成字符串，应能正常 parse。"""
    assert _has_potential_children({"triggered": "5"}, "x") is True
    assert _has_potential_children({"triggered": "0"}, "x") is False


# === 场景 10：空数组不应触发 ===
def test_empty_list_does_not_trigger():
    assert _has_potential_children({"rjcodes": []}, "fetch_check") is False
    assert _has_potential_children({"items": []}, "fetch_check") is False
    assert _has_potential_children({"child_rows": []}, "x") is False
