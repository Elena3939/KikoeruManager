"""社团补全 - DLsite 特典作品识别回归测试。"""
from __future__ import annotations

import pytest

from app.core.dlsite_service import DLsiteApiService


@pytest.fixture(scope="module")
def dlsite_service() -> DLsiteApiService:
    return DLsiteApiService()


def test_paid_work_with_bonus_in_title_is_not_bonus(dlsite_service: DLsiteApiService) -> None:
    """照 VoiceLinks：不看标题，只看 DLsite 结构化字段。"""
    product = {
        "work_name": "【簡体中文版】さすはめくらぶ。【早期購入特典つき】",
        "is_sale": True,
        "is_free": False,
        "is_oly": False,
        "wishlist_count": 46,
    }

    assert dlsite_service._product_info_indicates_bonus_work(product) is False


def test_voicelinks_bonus_rule_marks_bonus_work(dlsite_service: DLsiteApiService) -> None:
    product = {
        "is_sale": False,
        "is_free": True,
        "is_oly": True,
        "wishlist_count": 0,
    }

    assert dlsite_service._product_info_indicates_bonus_work(product) is True


def test_bool_false_wishlist_count_does_not_match_js_strict_zero(
    dlsite_service: DLsiteApiService,
) -> None:
    """JS 里 false !== 0，不能被 Python 的 False == 0 坑到。"""
    product = {
        "is_sale": False,
        "is_free": True,
        "is_oly": True,
        "wishlist_count": False,
    }

    assert dlsite_service._product_info_indicates_bonus_work(product) is False


def test_has_bonus_uses_dlsite_bonuses_array(dlsite_service: DLsiteApiService) -> None:
    assert (
        dlsite_service._product_info_indicates_has_bonus(
            {"bonuses": [{"workno": "RJ000001"}]}
        )
        is True
    )
    assert dlsite_service._product_info_indicates_has_bonus({"bonuses": []}) is False
