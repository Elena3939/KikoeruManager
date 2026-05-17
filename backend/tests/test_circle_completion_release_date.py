"""社团补全 - 预售作品发售日识别测试。

bug 现场：
- DLsite 对未排发售日的预售作品会把 ``release_date`` 写成 ``"未定"`` /
  ``"未確定"`` / ``"TBD"`` / ``"2026年 予定"`` 等非日期字符串。
- 原 ``_is_future_release_date`` 只匹配 ``YYYY-MM-DD`` 正则，遇到这种字符串
  直接 return False → 后端 ``item.is_unreleased=False`` → 前端
  WorkCard / WorkListRow 上的"📅 未发售"角标和蓝色边框光圈都不显示。
- 截图：发售日"未定"的预售作品在卡片上彻底"消失"成普通卡片。

修复后：
- 关键字（"未定" / "未確定" / "未定（予定）" / "予定" / "TBD" / "未发表" 等）
  优先判定为"未发售"，让前端正确显示预售徽章。
- 前端排序时 ``getWorkReleaseTimestamp`` 对这些字符串返回 0，
  ``missingWorks`` 排序逻辑会把 0 时间戳的作品恒留末尾（视为发售日最迟），
  这部分覆盖在 ``CircleCompletion.vue`` 的人工 review 里。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.circle_completion_service import CircleCompletionService


@pytest.fixture(scope="module")
def service() -> CircleCompletionService:
    return CircleCompletionService()


# ============ 关键字识别（核心修复）============


@pytest.mark.parametrize(
    "value",
    [
        "未定",
        "未確定",
        "未确定",
        "未発表",
        "未发表",
        "発売日未定",
        "发售日未定",
        "発売予定",
        "予定",
        "TBD",
        "tbd",
        "TBA",
        "Coming Soon",
        "coming soon",
        # 混合形态：DLsite 偶尔会写"2026年 予定"——含「予定」就视同预售
        "2026年 予定",
        # 带括号的形态
        "未定（予定）",
        "未定(予定)",
        # 前后带空白也应正确识别
        "  未定  ",
    ],
)
def test_release_date_keywords_classified_as_unreleased(
    service: CircleCompletionService, value: str
) -> None:
    """所有"未定 / TBD / 予定" 类关键字都应判定为未发售。"""
    assert service._is_future_release_date(value) is True, f"应判定为未发售：{value!r}"


# ============ 具体日期识别（不能回归）============


def test_future_concrete_date_is_unreleased(service: CircleCompletionService) -> None:
    """正常的未来日期仍然按未发售判定。"""
    future = date.today() + timedelta(days=30)
    value = future.strftime("%Y-%m-%d")
    assert service._is_future_release_date(value) is True


def test_past_concrete_date_is_released(service: CircleCompletionService) -> None:
    """正常的过去日期判定为已发售。"""
    past = date.today() - timedelta(days=30)
    value = past.strftime("%Y-%m-%d")
    assert service._is_future_release_date(value) is False


def test_today_is_released(service: CircleCompletionService) -> None:
    """当天判定为已发售（不严格大于 today）。"""
    today = date.today().strftime("%Y-%m-%d")
    assert service._is_future_release_date(today) is False


@pytest.mark.parametrize(
    "phase, base_day",
    [
        ("上旬", 10),
        ("中旬", 20),
        ("下旬", 28),
    ],
)
def test_future_year_month_phase_is_unreleased(
    service: CircleCompletionService, phase: str, base_day: int
) -> None:
    """"YYYY年MM月 上旬/中旬/下旬" 的未来时段应判定为未发售。"""
    future = date.today() + timedelta(days=180)
    value = f"{future.year}年{future.month}月{phase}"
    # 月份在未来肯定是未发售；day 取关键字对应的代表值，结果应该和正常日期一致
    assert service._is_future_release_date(value) is True


# ============ 边界场景 ============


def test_empty_value_is_not_unreleased(service: CircleCompletionService) -> None:
    """空字符串 / None：没有数据，不能误判为未发售。"""
    assert service._is_future_release_date("") is False
    assert service._is_future_release_date(None) is False
    assert service._is_future_release_date("   ") is False


def test_unrelated_text_without_keyword_is_not_unreleased(
    service: CircleCompletionService,
) -> None:
    """非日期、非关键字的垃圾文本不应被误判为未发售。"""
    assert service._is_future_release_date("ABC") is False
    assert service._is_future_release_date("Hello") is False
    # 数字串但不是合法年份格式
    assert service._is_future_release_date("99-99-99") is False


def test_invalid_date_components_are_not_unreleased(
    service: CircleCompletionService,
) -> None:
    """不合法的日期（如 2026-13-99）不应抛异常、应判定为非未发售。"""
    # 2026-13 月份非法 → datetime 构造抛 ValueError，应被吞掉返回 False
    assert service._is_future_release_date("2026-13-01") is False
