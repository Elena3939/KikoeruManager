"""DLsite 关联链：is_child / is_parent 分支 parent_workno 覆盖 original_workno 的回归。

★ 用户反馈现场（Lilith 社团补全）：
- 同一作品的简繁中翻译版 RJ01525048/RJ01525054、RJ01605924/RJ01605932、
  RJ01345085/RJ01413607/RJ01413616 等翻译对/组各占一张卡，"去重没了"。
- 根因：``_get_direct_linked_works`` 的 ``is_child`` 分支无条件
  ``result[parent_workno] = translation/<child.lang>``。
  直系翻译版的常见场景是 ``parent_workno == original_workno``（parent 就是原作 RJ），
  这一行会直接把刚写入的 ``original/JPN`` 覆盖成 ``translation/CHI_HANS``，
  整条链路里没有任何 ``work_type=='original'`` 入口，``resolve_canonical_rj``
  只能兜底用输入 rj 当 canonical，于是同一作品的简繁中版被分别写成多个
  独立 CircleWork 行、各占一张卡。
- ``is_parent`` 分支同样存在：当 target_rjcode 本身就是 original_workno
  （DLsite 偶尔把"原作 + 有翻译子节点"同时标 is_parent=True），
  ``result[target_rjcode] = translation/...`` 也会覆盖刚写入的 ``original/JPN``。

本测试钉死修复点：
1) is_child 分支：parent_workno == original_workno 时只留 original/JPN，
   不再被 translation 覆盖。
2) is_parent 分支：target_rjcode == original_workno 时，target 保留为 original/JPN。
3) get_linked_works(refresh=True) 能绕开 self.cache 旧值。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.dlsite_service import DLsiteApiService, LinkedWork, TranslationInfo


@pytest.fixture()
def service() -> DLsiteApiService:
    return DLsiteApiService()


@pytest.mark.asyncio
async def test_is_child_branch_keeps_original_when_parent_equals_original(
    service: DLsiteApiService,
) -> None:
    """简中翻译 RJ_C 的 parent == original == RJ_ORIG 时，关联链必须保留 original 标记。"""

    original_rj = "RJ01229406"
    simplified_rj = "RJ01393638"
    traditional_rj = "RJ01393625"

    async def fake_trans(rj: str) -> TranslationInfo:
        if rj == original_rj:
            # 原作 API 给的 translation_info：is_original=True，列出全部翻译版
            return TranslationInfo(is_original=True, lang="JPN")
        if rj == simplified_rj:
            return TranslationInfo(
                is_child=True,
                parent_workno=original_rj,
                original_workno=original_rj,
                lang="CHI_HANS",
            )
        if rj == traditional_rj:
            return TranslationInfo(
                is_child=True,
                parent_workno=original_rj,
                original_workno=original_rj,
                lang="CHI_HANT",
            )
        return TranslationInfo(lang="")

    async def fake_product(rj: str) -> dict:
        if rj == original_rj:
            return {
                "product": {
                    "workno": original_rj,
                    "language_editions": [
                        {"workno": simplified_rj, "lang": "CHI_HANS", "work_name": "[简中] xxx"},
                        {"workno": traditional_rj, "lang": "CHI_HANT", "work_name": "[繁中] xxx"},
                    ],
                }
            }
        return {"product": {"workno": rj}}

    service.get_translation_info = AsyncMock(side_effect=fake_trans)  # type: ignore[method-assign]
    service.get_product_info = AsyncMock(side_effect=fake_product)  # type: ignore[method-assign]

    # 三个 RJ 都查一遍，模拟社团补全 prepare_candidate 阶段对每个候选 RJ 各走一次
    # resolve_canonical_rj → get_linked_works 的真实流程。
    for entry_rj in (original_rj, simplified_rj, traditional_rj):
        service.cache.pop(f"linked_works:{entry_rj}", None)
        result = await service.get_linked_works(entry_rj, refresh=True)
        assert original_rj in result, f"从 {entry_rj} 出发应包含原作"
        assert result[original_rj].work_type == "original", (
            f"从 {entry_rj} 出发，原作 {original_rj} 必须保留 work_type=='original'，"
            f"实际 {result[original_rj].work_type}/{result[original_rj].lang}（"
            "parent_workno 误覆盖 original_workno 会让整条链路找不到 original 入口，"
            "翻译版会各占一张 CircleWork 卡)"
        )
        assert result[original_rj].lang == "JPN"


@pytest.mark.asyncio
async def test_is_parent_branch_with_real_translation_chain(
    service: DLsiteApiService,
) -> None:
    """``is_parent=True`` 在真实 DLsite 数据里指 "这是一个中间翻译版，下面还有子翻译"，
    原作 RJ 必然是另一个 RJ。原 BUG 不在这条路径上，但 is_parent 分支防御性
    修复后必须依然保证：original_workno != target_rjcode 时，原作 RJ 仍是 original/JPN，
    target 自身是 translation/<lang>，child 是 child_translation。"""

    real_original = "RJ_ORIG"
    mid_translation = "RJ_MID"
    sub_translation = "RJ_SUB"

    async def fake_trans(rj: str) -> TranslationInfo:
        if rj == mid_translation:
            return TranslationInfo(
                is_parent=True,
                original_workno=real_original,
                child_worknos=[sub_translation],
                lang="CHI_HANS",
            )
        if rj == sub_translation:
            return TranslationInfo(
                is_child=True,
                parent_workno=mid_translation,
                original_workno=real_original,
                lang="CHI_HANS",
            )
        if rj == real_original:
            return TranslationInfo(is_original=True, lang="JPN")
        return TranslationInfo(lang="")

    service.get_translation_info = AsyncMock(side_effect=fake_trans)  # type: ignore[method-assign]
    service.get_product_info = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda rj: {
            "product": {
                "workno": rj,
                "language_editions": [{"workno": mid_translation, "lang": "CHI_HANS"}]
                if rj == real_original
                else [],
            }
        },
    )

    # 从中间翻译版入口查：result 必须三个 RJ 都齐，原作 RJ 是 original，
    # mid 是 translation，sub 是 child_translation——这是 DLsite 真实数据里
    # ``is_parent=True`` 唯一的正确解读。
    service.cache.pop(f"linked_works:{mid_translation}", None)
    service.cache.pop(f"linked_works:{real_original}", None)
    result = await service.get_linked_works(mid_translation, refresh=True)

    assert result[real_original].work_type == "original"
    assert result[real_original].lang == "JPN"
    assert result[mid_translation].work_type == "translation"
    assert result[sub_translation].work_type == "child_translation"


@pytest.mark.asyncio
async def test_get_linked_works_refresh_clears_cached_linked_works(
    service: DLsiteApiService,
) -> None:
    """refresh=True 必须把 self.cache[linked_works:...] 旧值清掉再重算，
    保证用户主动强刷时能拿到修复后的代码新结果，而不是 24h 内的旧 BUG 结果。"""

    target_rj = "RJ01413648"
    cache_key = f"linked_works:{target_rj}"

    # 1. 预先把"旧 BUG 的错误关联链"塞进 cache（target 被错标成 translation/JPN）
    from datetime import datetime

    service.cache[cache_key] = {
        "data": {
            target_rj: LinkedWork(workno=target_rj, work_type="translation", lang="JPN"),
        },
        "timestamp": datetime.now(),
    }

    # 2. mock fresh API：现在是修复后版本，is_original=True 应该让 target 标 original/JPN
    service.get_translation_info = AsyncMock(  # type: ignore[method-assign]
        return_value=TranslationInfo(is_original=True, lang="JPN"),
    )
    service.get_product_info = AsyncMock(  # type: ignore[method-assign]
        return_value={"product": {"workno": target_rj, "language_editions": []}},
    )

    # 3. 不带 refresh 应命中旧 cache（保留 24h TTL 行为，业务侧能区分）
    result_cached = await service.get_linked_works(target_rj)
    assert result_cached[target_rj].work_type == "translation", "不带 refresh 应命中旧 cache"

    # 4. refresh=True 必须清掉旧 cache 重新跑，target 现在是 original/JPN
    result_fresh = await service.get_linked_works(target_rj, refresh=True)
    assert result_fresh[target_rj].work_type == "original"
    assert result_fresh[target_rj].lang == "JPN"
