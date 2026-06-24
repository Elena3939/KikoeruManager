"""Kikoeru 查重 linkage 广义匹配回归测试。

★ 用户痛点：RJ01407907 这类原作没上 Kikoeru、但简中翻译版上了的作品，搜原作 RJ
时 Kikoeru 实际只回了简中翻译版的 work（``id`` 是翻译版 RJ 的数字部分、且没有
``sourceWorkno`` 字段）。修复前的 ``_parse_search_result`` 严格 1:1 匹配会误报
"整条链路未命中"。

本文件的 case 都直接构造 ``KikoeruDuplicateService`` 实例并打 ``_parse_search_result``，
不走 HTTP，专注验证：

1. 严格匹配优先：候选里同时含查询 RJ 时仍判为 ``exact``。
2. linkage 广义匹配：候选里只含关联 RJ 时判为 ``linkage_match``，
   ``matched_rjcode`` 指向 Kikoeru 实际命中的关联 RJ。
3. 没有 ``extra_match_rjcodes`` 时不会"乱匹配"，保留旧行为。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.kikoeru_duplicate_service import (
    KikoeruCheckResult,
    KikoeruDuplicateService,
    KikoeruServerConfig,
)


@pytest.fixture()
def service() -> KikoeruDuplicateService:
    """构造一个最小可用的 service，只用于跑纯解析逻辑。"""
    config = KikoeruServerConfig(
        enabled=True,
        server_url="http://kikoeru.local:8088",
        username="tester",
        password="tester",
        api_token="dummy-token",
        token_expires=99999999999,
        timeout=5,
        cache_ttl=60,
    )
    return KikoeruDuplicateService(config=config)


def _make_translation_only_response(translation_work_id: int) -> dict:
    """模拟 Kikoeru 仅回一条简中翻译版 work 的搜索响应。

    关键：不带 ``sourceWorkno`` / ``source_workno`` / ``workno`` / ``rjcode`` 字段，
    模拟"用户痛点的 Kikoeru 部署"——这样才能真实复现严格匹配漏判。
    """
    return {
        "works": [
            {
                "id": translation_work_id,
                "title": "[简体中文版] テスト作品",
                "circle": {"name": "桃色CODE"},
                "tags": [{"name": "简体中文版"}],
            }
        ],
        "pagination": {"total_pages": 1},
    }


def test_strict_match_still_takes_priority(service: KikoeruDuplicateService) -> None:
    """严格匹配命中时不应该走 linkage 广义匹配。"""
    data = {
        "works": [
            {
                "id": 1407907,
                "title": "原作 work",
                "circle": {"name": "桃色CODE"},
                "tags": [],
            }
        ]
    }
    extra = {"RJ01407907", "RJ01433195"}

    result = service._parse_search_result("RJ01407907", data, extra_match_rjcodes=extra)

    assert result.is_found is True
    assert result.match_type == "exact"
    assert result.matched_rjcode == "RJ01407907"
    assert result.work_id == 1407907


def test_linkage_match_recovers_translation_only_response(service: KikoeruDuplicateService) -> None:
    """RJ01407907 类痛点回归：搜原作但 Kikoeru 只回简中翻译版，应判为 linkage_match。"""
    data = _make_translation_only_response(translation_work_id=1433195)
    extra = {"RJ01407907", "RJ01433195", "RJ01449055", "RJ01449056"}

    result = service._parse_search_result("RJ01407907", data, extra_match_rjcodes=extra)

    assert result.is_found is True, "关联链广义匹配未生效，会重现整条链路未命中的 bug"
    assert result.match_type == "linkage_match"
    assert result.matched_rjcode == "RJ01433195"
    assert result.work_id == 1433195
    assert result.title == "[简体中文版] テスト作品"


def test_linkage_set_excludes_queried_rj_to_avoid_self_match(service: KikoeruDuplicateService) -> None:
    """linkage set 即便包含查询 RJ 自己，也不应在严格匹配失败后错误命中自己。

    这个 case 用 ``id=9999999`` 不在任何 RJ 集合里，确保第二轮严格按交集判定，
    防止 ``normalized_extra`` 没把查询 RJ 剔出去时退化为"任意 work 都命中"。
    """
    data = {
        "works": [
            {
                "id": 9999999,
                "title": "完全无关作品",
                "circle": {"name": "Other"},
            }
        ]
    }
    # 集合里塞了查询 RJ 自己，但不含 RJ09999999
    extra = {"RJ01407907"}

    result = service._parse_search_result("RJ01407907", data, extra_match_rjcodes=extra)

    assert result.is_found is False
    assert result.match_type == "exact"  # 默认值，未被改写
    assert result.matched_rjcode == ""


def test_no_linkage_context_preserves_strict_only_behavior(service: KikoeruDuplicateService) -> None:
    """没传 extra_match_rjcodes 时，简中翻译版返回必须仍判为未命中——保留旧语义。"""
    data = _make_translation_only_response(translation_work_id=1433195)

    result = service._parse_search_result("RJ01407907", data)

    assert result.is_found is False
    assert result.matched_rjcode == ""


def test_maybe_cache_skips_linkage_match(service: KikoeruDuplicateService) -> None:
    """linkage_match 不能进主缓存，否则无上下文调用方会拿到诡异命中。"""
    data = _make_translation_only_response(translation_work_id=1433195)
    extra = {"RJ01407907", "RJ01433195"}

    result = service._parse_search_result("RJ01407907", data, extra_match_rjcodes=extra)
    assert result.match_type == "linkage_match"  # 前置确认

    # 模拟 check_duplicate 末段逻辑：use_cache=True 但 result 是 linkage_match
    service._maybe_cache_result("RJ01407907", result, use_cache=True)
    assert service._get_cache("RJ01407907") is None, "linkage_match 不应被写入主缓存"


def test_search_url_does_not_restrict_nsfw(service: KikoeruDuplicateService) -> None:
    """RJ 查重主入口 search URL **不允许**夹带 ``nsfw`` 过滤参数。

    回归保护：本工具管的全是 R18 ASMR 作品；任何形如 ``nsfw=0`` 的过滤都会让整条
    RJ 链路（含简中翻译版）从 ``works`` 里消失，外面看就是用户反馈的"整条链路未
    命中"。所以这里钉死：URL 里不能出现任意 ``nsfw=…`` 参数，让 Kikoeru 服务端
    按当前账号自身的偏好放行结果。
    """
    url = service._build_search_url("RJ01407907")
    assert "nsfw=" not in url, f"主搜 URL 不应包含任何 nsfw 过滤: {url}"
    assert "keyword=RJ01407907" in url
    # 与油猴脚本 / circle 搜索模板对齐
    assert "isAdvance=0" in url
    assert "lyric=" in url


def test_maybe_cache_writes_strict_match(service: KikoeruDuplicateService) -> None:
    """严格命中正常入缓存。"""
    data = {
        "works": [
            {
                "id": 1407907,
                "title": "exact",
                "circle": {"name": "C"},
                "tags": [],
            }
        ]
    }
    result = service._parse_search_result("RJ01407907", data)
    assert result.match_type == "exact"

    # 给 result 补一个非空 subtitle_check_source，绕开 _get_cache 里那条
    # "命中但没字幕来源就当过期"的清理逻辑（见 _get_cache 实现）。
    result.subtitle_check_source = "search_only"
    service._maybe_cache_result("RJ01407907", result, use_cache=True)
    cached = service._get_cache("RJ01407907")
    assert cached is not None, "exact 命中应该写入缓存"
    assert cached.matched_rjcode == "RJ01407907"


@pytest.mark.asyncio
async def test_check_duplicate_with_linkages_raises_when_dlsite_chain_is_unknown(
    service: KikoeruDuplicateService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DLsite 返回 unknown 链时，Kikoeru 查重必须直接报错。"""

    monkeypatch.setattr(
        "app.core.kikoeru_duplicate_service.get_dlsite_service",
        lambda: SimpleNamespace(
            get_linked_works=AsyncMock(
                return_value={
                    "RJ01407907": SimpleNamespace(
                        workno="RJ01407907",
                        work_type="unknown",
                        lang="UNKNOWN",
                    )
                }
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "check_duplicate",
        AsyncMock(return_value=KikoeruCheckResult(rjcode="RJ01407907")),
    )

    with pytest.raises(RuntimeError, match="DLsite 关联链查询失败"):
        await service.check_duplicate_with_linkages("RJ01407907")


def test_safe_headers_for_log_masks_authorization(service: KikoeruDuplicateService) -> None:
    headers = service._safe_headers_for_log({
        "Accept": "application/json",
        "Authorization": "Bearer secret-token-value",
    })

    rendered = repr(headers)
    assert "secret-token-value" not in rendered
    assert "Bearer ********" in rendered or headers.get("Authorization") == "********"
    assert headers["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_check_duplicate_reuses_inflight_for_same_rj(service: KikoeruDuplicateService, monkeypatch) -> None:
    calls = 0

    async def fake_impl(rjcode, use_cache=True, extra_match_rjcodes=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return KikoeruCheckResult(is_found=True, rjcode=rjcode, matched_rjcode=rjcode)

    monkeypatch.setattr(service, "_check_duplicate_impl", fake_impl)

    first, second = await asyncio.gather(
        service.check_duplicate("RJ01234567"),
        service.check_duplicate("RJ01234567"),
    )

    assert calls == 1
    assert first.rjcode == "RJ01234567"
    assert second.rjcode == "RJ01234567"
