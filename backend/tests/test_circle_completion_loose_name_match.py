"""社团补全 - 宽松社团名匹配回归测试。

bug 现场：用户输入的 circle_query = "悪女名鑑(常世常闇々)"（Kikoeru 把
系列名拼进社团名），DLsite 上的 maker_name 是裸社团名 "常世常闇々"。
旧实现只做单向 ``normalize_circle_name(query) in normalize_circle_name(maker_name)``，
长 query 永远命中不了短 maker_name，``_resolve_seed_maker_id`` 因此拿不到
maker_id，整条社团补全链路只能退回关键字搜索（``max_pages=2``，最多
60 个 RJ），最终聚合后只剩 Kikoeru 已知的几个，DLsite 主页上其余作品
全部被错杀。

这里的测试只覆盖最小的 ``_circle_name_loose_match`` 行为，但它就是整条
匹配链的统一入口；只要它保持双向 substring + 最小长度阈值的语义，上层
``_resolve_seed_maker_id`` / ``fetch_candidate`` / ``_collect_local_circle_candidates``
/ ``_candidate_belongs_to_identity`` 就不会再出现"全社团作品被误删"。
"""
from __future__ import annotations

import pytest

from app.core.circle_completion_service import CircleCompletionService


@pytest.fixture(scope="module")
def service() -> CircleCompletionService:
    return CircleCompletionService()


def test_loose_match_query_with_series_prefix_matches_bare_maker_name(service: CircleCompletionService) -> None:
    # bug 复现现场：query 比 maker_name 长，旧实现会返 False
    assert service._circle_name_loose_match("悪女名鑑(常世常闇々)", "常世常闇々") is True


def test_loose_match_forward_substring_still_works(service: CircleCompletionService) -> None:
    # 正向 substring（DLsite 上社团带 "サークル" 后缀，Kikoeru 上是裸名）
    assert service._circle_name_loose_match("常世常闇々", "常世常闇々サークル") is True


def test_loose_match_exact_equal(service: CircleCompletionService) -> None:
    assert service._circle_name_loose_match("常世常闇々", "常世常闇々") is True


def test_loose_match_unrelated_circle_rejected(service: CircleCompletionService) -> None:
    # 没有公共 substring，应当拒绝，避免把不相关社团的作品当成自己的
    assert service._circle_name_loose_match("常世常闇々", "別の社団") is False


def test_loose_match_short_maker_name_not_engulfed_by_long_query(service: CircleCompletionService) -> None:
    # 反向匹配的最低长度阈值：2 字 maker_name "AB" 不应该被任意含 AB 的 query 命中
    # 否则会导致大量误识别。CJK 信息密度高，3 字符是当前阈值。
    assert service._circle_name_loose_match("ABCDE-Studio", "AB") is False


def test_loose_match_handles_decorative_symbols(service: CircleCompletionService) -> None:
    # ○●☆♡ 等装饰符在 normalize 时会被去掉，不影响匹配
    assert service._circle_name_loose_match("J○大好き", "J●大好き") is True


def test_loose_match_empty_inputs_dont_block_pipeline(service: CircleCompletionService) -> None:
    # 任意一侧空时返回 True，让上层根据 maker_id 等更强信号决策，避免
    # 因 metadata 残缺导致整组候选被误删。
    assert service._circle_name_loose_match("", "常世常闇々") is True
    assert service._circle_name_loose_match("常世常闇々", "") is True
    assert service._circle_name_loose_match("", "") is True


# ----- _build_search_keyword_variants -----
# Kikoeru 是按 works keyword 搜作品再抽 circle.id 的，整串长 query 经常
# 0 命中，必须把括号内 / 外的子 keyword 拆出来重试。

def test_keyword_variants_keeps_raw_first_then_inner_then_outer(service: CircleCompletionService) -> None:
    variants = service._build_search_keyword_variants("悪女名鑑(常世常闇所々)")
    assert variants[0] == "悪女名鑑(常世常闇所々)"  # 原 query 必须排第一
    assert "常世常闇所々" in variants  # 括号内（真实社团名）必须被拆出
    assert "悪女名鑑" in variants  # 括号外（系列名前缀）必须被拆出


def test_keyword_variants_handles_fullwidth_brackets(service: CircleCompletionService) -> None:
    # 用户可能在中文输入法下打全角括号，NFKC 归一化后才剥离
    variants = service._build_search_keyword_variants("悪女名鑑（常世常闇所々）")
    assert "常世常闇所々" in variants
    assert "悪女名鑑" in variants


def test_keyword_variants_skips_too_short_tokens(service: CircleCompletionService) -> None:
    # 单字 token 不应该出现在变种里，否则会大量误命中其他无关 circle
    variants = service._build_search_keyword_variants("A 悪女名鑑")
    assert "A" not in variants
    assert "悪女名鑑" in variants


def test_keyword_variants_no_duplicates(service: CircleCompletionService) -> None:
    variants = service._build_search_keyword_variants("常世常闇所々")
    # 不带括号的 query 不应该把自己再添加一次
    assert variants == ["常世常闇所々"]


def test_keyword_variants_empty_input(service: CircleCompletionService) -> None:
    assert service._build_search_keyword_variants("") == []
    assert service._build_search_keyword_variants(None) == []  # type: ignore[arg-type]
