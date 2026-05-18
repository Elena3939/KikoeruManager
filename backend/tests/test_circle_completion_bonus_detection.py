"""社团补全 - DLsite 特典作品识别回归测试。"""
from __future__ import annotations

from typing import Any, Dict, Optional

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


@pytest.mark.asyncio
async def test_get_product_bonus_info_raises_when_payload_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """root cause 修复：``_fetch_product_info_ajax_payload`` 返 None 时必须 raise。

    历史 bug：拉空时返回 ``{is_bonus_work: False, has_bonus: False}`` 不抛异常，
    上游 ``_apply_dlsite_bonus_info`` 顺利打了 ``bonus_info_checked_at=NOW()``，
    从此 ``lazy_refresh_bonus_for_cached_rjcodes`` 永远跳过，特典漏判救不回。
    必须 raise 让 except 分支保留 ``bonus_info_checked_at=None``。
    """
    service = DLsiteApiService()

    async def _stub_payload(rjcode: str, locale: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return None

    monkeypatch.setattr(service, "_fetch_product_info_ajax_payload", _stub_payload)

    with pytest.raises(RuntimeError, match=r"未返回.*的有效 payload"):
        await service.get_product_bonus_info("RJ01527756")


@pytest.mark.asyncio
async def test_get_product_bonus_info_returns_dict_when_payload_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常路径：payload 是有效 dict 时返回 is_bonus_work / has_bonus，不抛异常。"""
    service = DLsiteApiService()

    async def _stub_payload(rjcode: str, locale: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return {
            "is_sale": False,
            "is_free": True,
            "is_oly": True,
            "wishlist_count": 0,
            "bonuses": [{"workno": "RJ_BONUS"}],
        }

    monkeypatch.setattr(service, "_fetch_product_info_ajax_payload", _stub_payload)

    result = await service.get_product_bonus_info("RJ01527756")

    assert result == {"is_bonus_work": True, "has_bonus": True}
