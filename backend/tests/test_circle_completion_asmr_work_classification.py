"""社团补全 - 音声 / 非音声候选分类回归测试。

bug 现场：用户跑 Lilith 社团补全时，``RJ154958《対魔忍ユキカゼ2》`` 被错误
索引进 ``circle_works``，前端显示在 Lilith 的作品卡列表里。这是个 ADV 游戏
（``work_type=ADV``、文件格式 EXE），但 DLsite 上有完整声优配音
（氷室百合 / 佐藤遼佳 / 花南）。

旧实现两个弱判定一起放水：

1. ``_metadata_looks_like_asmr_work`` 在 tags / 标题没任何音声 marker 时，
   仅凭 ``cvs`` 非空就 return True。
2. ``_product_looks_like_asmr_work`` 只用 ``work_type == "SOU"`` 做白名单，
   非 SOU code 落到下游靠 category_text + voice_by 判定，遇到 product 数据
   残缺时还会被 voice_by 兜底带进 True。

修复：

1. 删 ``_metadata_looks_like_asmr_work`` 的 cvs 兜底分支。
2. ``_product_looks_like_asmr_work`` 加 work_type 强信号：非空且非 SOU 立刻
   return False，不再走 voice_by 兜底。

这两个改动都必须有测试守住，避免 ADV/RPG/MUS/COM 等非音声 work_type 的作品
未来再被误索引。
"""
from __future__ import annotations

import pytest

from app.core.circle_completion_service import CircleCompletionService


@pytest.fixture(scope="module")
def service() -> CircleCompletionService:
    return CircleCompletionService()


# ----- _metadata_looks_like_asmr_work -----


def test_metadata_only_cvs_no_audio_marker_is_not_asmr(service: CircleCompletionService) -> None:
    """RJ154958《対魔忍ユキカゼ2》案例：tags 只有 genre 标签 + cvs 非空，
    既不能进 audio_package_text 也没非音声 marker。旧实现凭 cvs 直接 True，
    会让 ADV 游戏被误索引。新实现必须 return False，让上层走 product 权威判定。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "対魔忍ユキカゼ2",
        "tags": ["コスプレ", "制服", "ネトラレ", "陵辱", "褐色", "貧乳"],
        "cvs": ["氷室百合", "佐藤遼佳", "花南"],
    }) is False


def test_metadata_audio_tag_still_recognized_even_without_cvs(service: CircleCompletionService) -> None:
    """tags 里有音声 marker 时仍能识别为音声作品（不依赖 cvs）。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "夜の囁き",
        "tags": ["音声・ASMR", "バイノーラル"],
        "cvs": [],
    }) is True


def test_metadata_audio_title_marker_still_recognized(service: CircleCompletionService) -> None:
    """标题含 KU100/バイノーラル 等强信号时优先识别。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "【KU100】耳元囁きASMR",
        "tags": [],
        "cvs": [],
    }) is True


def test_metadata_weak_theme_tags_are_not_audio_shape(service: CircleCompletionService) -> None:
    """催眠 / 治愈 / 调教是题材标签，不是文件形态。ADV/RPG 游戏也大量使用这些 tag，
    不能仅凭它们把作品放进社团补全。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "カーラ The Blood Lord",
        "tags": ["催眠", "调教"],
        "cvs": [],
    }) is False


def test_metadata_with_audio_tag_and_cvs_still_asmr(service: CircleCompletionService) -> None:
    """tags 含音声 marker + cvs 非空 → 音声作品（保持向后兼容，回归
    ``test_non_audio_marker_does_not_treat_rpgx_brand_as_game``）。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "【対魔忍RPGX】神大路瑠亜ASMR",
        "tags": ["音声・ASMR", "ASMR"],
        "cvs": ["麦芽ぷりん"],
    }) is True


def test_metadata_non_audio_tag_takes_precedence(service: CircleCompletionService) -> None:
    """tags 同时有"音声"和"PDF/技术书"时，文件形态级别的非音声 marker 优先级最高。"""
    assert service._metadata_looks_like_asmr_work({
        "work_name": "音声作品のつくりかた",
        "tags": ["ASMR", "人头麦", "PDF", "技术书"],
        "cvs": ["某声优"],
    }) is False


# ----- _product_looks_like_asmr_work -----


def test_product_work_type_sou_is_asmr(service: CircleCompletionService) -> None:
    """DLsite work_type=SOU 是音声作品的权威白名单信号。"""
    assert service._product_looks_like_asmr_work({
        "work_type": "SOU",
        "work_name": "夜の囁き",
        "creaters": {"voice_by": [{"name": "某声优"}]},
    }) is True


def test_product_work_type_adv_with_voice_by_is_not_asmr(service: CircleCompletionService) -> None:
    """RJ154958 案例：work_type=ADV + 声优配音齐全。绝不能因为 voice_by 非空
    就误判为音声作品。"""
    assert service._product_looks_like_asmr_work({
        "work_type": "ADV",
        "work_name": "対魔忍ユキカゼ2",
        "creaters": {
            "voice_by": [
                {"name": "氷室百合"},
                {"name": "佐藤遼佳"},
                {"name": "花南"},
            ]
        },
        "genres": [
            {"name": "コスプレ"},
            {"name": "制服"},
            {"name": "ネトラレ"},
        ],
    }) is False


@pytest.mark.parametrize(
    "non_sou_code",
    ["RPG", "ADV", "ACN", "SLN", "TBL", "QIZ", "DGT", "MUS", "ICG", "MOV", "COM", "NRE", "IMG", "GAM"],
)
def test_product_non_sou_work_type_is_not_asmr(
    service: CircleCompletionService,
    non_sou_code: str,
) -> None:
    """所有非 SOU 的 work_type code（包括 voice_by 极常见的 RPG/ADV）都不是
    音声作品。这是 DLsite 给出的权威分类信号，不接受下游 voice_by / cvs 兜底。"""
    assert service._product_looks_like_asmr_work({
        "work_type": non_sou_code,
        "work_name": "samplework",
        "creaters": {"voice_by": [{"name": "某声优"}]},
    }) is False


def test_product_empty_work_type_falls_back_to_category(service: CircleCompletionService) -> None:
    """work_type 缺失时（DLsite 数据残缺）才进入 category_text / voice_by 兜底。
    category 命中音声 marker → True。"""
    assert service._product_looks_like_asmr_work({
        "work_type": "",
        "work_name": "夜の囁き",
        "category": "音声・ASMR",
    }) is True


def test_product_empty_work_type_with_only_voice_by_is_asmr(service: CircleCompletionService) -> None:
    """work_type 缺失 + category 全空 + 有 voice_by → 走声优兜底判 True。
    这是 DLsite 数据极度残缺时的最后一道兜底，正常情况不应触发。"""
    assert service._product_looks_like_asmr_work({
        "work_type": "",
        "work_name": "untitled",
        "creaters": {"voice_by": [{"name": "某声优"}]},
    }) is True


def test_product_empty_dict_returns_none(service: CircleCompletionService) -> None:
    """完全没有 product 信息时返回 None（不做任何判定，让上层 fallback 处理）。"""
    assert service._product_looks_like_asmr_work({}) is None
    assert service._product_looks_like_asmr_work(None) is None


# ----- _classify_asmr_work_candidate（端到端） -----


@pytest.mark.asyncio
async def test_classify_adv_game_via_product_work_type(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端验证：metadata 缓存里只有 genre + cvs，无任何音声 marker。
    新链路下 _metadata_looks_like_asmr_work 返回 False，然后调 DLsite product_info
    用 work_type=ADV 权威判定 False，整体返回 False。"""

    async def _fake_get_product_info(rjcode: str, **kwargs):
        return {
            "product": {
                "work_type": "ADV",
                "work_name": "対魔忍ユキカゼ2",
                "creaters": {"voice_by": [{"name": "氷室百合"}]},
                "genres": [{"name": "コスプレ"}],
            }
        }

    monkeypatch.setattr(service.dlsite_service, "get_product_info", _fake_get_product_info)

    metadata = {
        "work_name": "対魔忍ユキカゼ2",
        "tags": ["コスプレ", "制服", "ネトラレ"],
        "cvs": ["氷室百合", "佐藤遼佳", "花南"],
    }
    result = await service._classify_asmr_work_candidate("RJ154958", metadata)
    assert result is False


@pytest.mark.asyncio
async def test_classify_adv_game_overrides_weak_metadata_theme(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lilith 现场：游戏 metadata 只有催眠 / 调教这类题材标签，product_info 返回
    work_type=ADV。最终必须按 DLsite 权威分类判 False。"""

    async def _fake_get_product_info(rjcode: str, **kwargs):
        return {
            "product": {
                "work_type": "ADV",
                "work_name": "カーラ The Blood Lord",
            }
        }

    monkeypatch.setattr(service.dlsite_service, "get_product_info", _fake_get_product_info)

    result = await service._classify_asmr_work_candidate(
        "RJ096156",
        {"work_name": "カーラ The Blood Lord", "tags": ["催眠", "调教"], "cvs": []},
    )
    assert result is False


@pytest.mark.asyncio
async def test_classify_real_asmr_via_metadata_audio_marker(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真音声作品 tags 含 ``音声・ASMR``，metadata 阶段就能判 True，不再多打一次 product。"""
    call_count = {"n": 0}

    async def _spy_get_product_info(rjcode: str, **kwargs):
        call_count["n"] += 1
        return {"product": {"work_type": "SOU", "work_name": "x"}}

    monkeypatch.setattr(service.dlsite_service, "get_product_info", _spy_get_product_info)

    metadata = {
        "work_name": "夜の囁き",
        "tags": ["音声・ASMR"],
        "cvs": ["某声优"],
    }
    result = await service._classify_asmr_work_candidate("RJ123456", metadata)
    assert result is True
    # 命中 metadata 强信号后不再多打一次 DLsite product 接口
    assert call_count["n"] == 0
