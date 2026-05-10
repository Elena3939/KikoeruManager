"""DLsite 关联链不再做"前台公开可见性"过滤的回归测试。

★ 用户痛点（RJ01407907 类）：DLsite 父作品 API 的 ``language_editions`` 列表里
明明列了 6 个翻译版（ENG/CHI_HANS/CHI_HANT/KO_KR/IND/THA），但因为这些 R18
翻译版的 DLsite 公开匿名 API 会 404（需要登录 / 年龄校验），原来的
``_is_public_work_available`` 过滤会把它们全部判成"前台不可见"剔出关联链。
结果就是 Kikoeru 查重只查了原作 1 条 RJ，整条链路误报"未命中"。

油猴脚本 ``view.txt`` 的 ``getLinkedWorks`` 是无条件信 ``language_editions``，
本工具现在对齐这一行为。本测试钉死：父作品 API 给了几个翻译版，关联链就要
完整带上几个，不做任何 "is_public" 过滤。
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.dlsite_service import DLsiteApiService, TranslationInfo


@pytest.fixture()
def service() -> DLsiteApiService:
    return DLsiteApiService()


@pytest.mark.asyncio
async def test_original_keeps_all_language_editions_without_public_filter(
    service: DLsiteApiService,
) -> None:
    """父作品 API 给的所有翻译版都必须出现在关联链里。"""

    # 模拟 RJ01407907 是原作；DLsite 父作品 API 列了 6 个翻译版。
    parent_workno = "RJ01407907"
    editions = [
        {"workno": "RJ01433195", "lang": "ENG", "work_name": "[英文] xxx"},
        {"workno": "RJ01449055", "lang": "CHI_HANS", "work_name": "[简中] xxx"},
        {"workno": "RJ01450681", "lang": "CHI_HANT", "work_name": "[繁中] xxx"},
        {"workno": "RJ01412948", "lang": "KO_KR", "work_name": "[韩文] xxx"},
        {"workno": "RJ01415279", "lang": "IND", "work_name": "[印尼] xxx"},
        {"workno": "RJ01418062", "lang": "THA", "work_name": "[泰语] xxx"},
    ]

    service.get_translation_info = AsyncMock(  # type: ignore[method-assign]
        return_value=TranslationInfo(is_original=True, lang="JPN"),
    )
    service.get_product_info = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "product": {
                "workno": parent_workno,
                "language_editions": editions,
            }
        }
    )

    # 这里一旦还有人偷偷塞回来 ``_is_public_work_available`` 调用并返回 False，
    # 测试就要立刻把这种回退暴露出来。所以把它强制 mock 成永远 False，看后面
    # 关联链有没有被过滤。
    service._is_public_work_available = AsyncMock(return_value=False)  # type: ignore[method-assign]

    result = await service.get_linked_works(parent_workno)

    expected = {parent_workno, *(e["workno"] for e in editions)}
    assert set(result.keys()) == expected, (
        f"关联链丢失翻译版（被 _is_public_work_available 误过滤）: "
        f"got={sorted(result.keys())} expected={sorted(expected)}"
    )

    # 原作类型 / 翻译版类型也要打对，避免后面 broad-match 用错 lang
    assert result[parent_workno].work_type == "original"
    for edition in editions:
        node = result[edition["workno"]]
        assert node.work_type == "translation", f"{edition['workno']} 应是 translation"
        assert node.lang == edition["lang"], f"{edition['workno']} lang 不对"


@pytest.mark.asyncio
async def test_skips_editions_without_workno(service: DLsiteApiService) -> None:
    """``language_editions`` 里没 workno 的脏条目仍要被跳过，但只是因为字段空，
    不能再用公开可见性这种业务过滤。"""
    service.get_translation_info = AsyncMock(  # type: ignore[method-assign]
        return_value=TranslationInfo(is_original=True, lang="JPN"),
    )
    service.get_product_info = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "product": {
                "workno": "RJ01407907",
                "language_editions": [
                    {"workno": "", "lang": "ENG"},          # 脏数据
                    {"workno": None, "lang": "CHI_HANS"},   # 脏数据
                    {"workno": "RJ01433195", "lang": "ENG"},
                ],
            }
        }
    )
    service._is_public_work_available = AsyncMock(return_value=False)  # type: ignore[method-assign]

    result = await service.get_linked_works("RJ01407907")
    assert set(result.keys()) == {"RJ01407907", "RJ01433195"}
