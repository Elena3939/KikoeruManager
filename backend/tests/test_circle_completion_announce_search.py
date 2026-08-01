"""社团补全 - DLsite announce keyword 搜索的伪候选拒收回归测试。

bug 现场（用户复测「いっしんふらん」DLsite 主页 16 个真作品 → 系统抓到 115 个候选）：

1. ``/maniax/announce/list/day/=/keyword/XXX``：page 1 200 OK 抓到一堆全站新预告
   RJ（DLsite 在 keyword 没匹配时直接返回回退页），page 2 才 301 重定向。代码
   在 page 2 看到 redirect 时丢弃了第一个 template 的 ``attempt_found``，但
   ``continue`` 跳到下一个 template ``home-touch/announce/list/day``。

2. ``home-touch`` 域名在 keyword 没命中时**不返 redirect、直接 200 OK 返回
   home-touch 端的全站新预告列表**，``re.findall`` 把推荐位 / 广告位 / 最新预告
   里的 RJ 全扫成 keyword 命中，commit 到 ``found``，污染 100+ 个伪候选。

修复：任一 template 出现 ``redirect_aborted`` → 立即整个函数 abort 返空，不再
trial 后续 template。redirect 是 DLsite 给的强信号"keyword 在 announce 上 0
命中"，后续 template 的 200 OK 内容必然是回退页污染。

这套测试只覆盖最核心的"redirect 出现就立即停"行为，不依赖真实 HTTP，用最小
mock httpx client 验证 URL 调用次数。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import pytest

from app.core.circle_completion_service import CircleCompletionService


class _MockResponse:
    def __init__(self, status_code: int, text: str = "", headers: Optional[Dict[str, str]] = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _MockHttpxClient:
    """记录所有 GET URL，按 route_handler 返回 mock response。"""

    def __init__(self, route_handler: Callable[[str], _MockResponse]) -> None:
        self.calls: List[str] = []
        self.route_handler = route_handler

    async def get(self, url: str, **_kwargs: Any) -> _MockResponse:
        self.calls.append(url)
        result = self.route_handler(url)
        if isinstance(result, BaseException):
            raise result
        return result


def _work_card(rjcode: str, maker_id: str, maker_name: str) -> str:
    return (
        f'<dd class="work_name"><a href="https://www.dlsite.com/maniax/work/=/product_id/{rjcode}.html">作品</a></dd>'
        f'<dd class="maker_name"><a href="https://www.dlsite.com/maniax/circle/profile/=/maker_id/{maker_id}.html">'
        f'{maker_name}</a></dd>'
    )


@pytest.fixture
def service() -> CircleCompletionService:
    return CircleCompletionService()


@pytest.mark.asyncio
async def test_announce_search_aborts_entire_function_when_first_template_redirects(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第一个 template page 2 redirect 后，**绝不能**再去 try home-touch template。

    bug 现场：home-touch 域名不返 redirect 但内容也是回退页，伪候选会被 commit。
    """
    # 全站新作页面里出现的 RJ（page 1 抓到的"伪候选"）
    fake_recommended_rjcodes_html = "".join(
        _work_card(f"RJ0162{n:04d}", "RG99999", "いっしんふらん") for n in range(0, 30)
    )

    def route_handler(url: str) -> _MockResponse:
        # 第一个 template /maniax/announce/list/day/=/keyword/...
        if "/maniax/announce/list/day/=/keyword/" in url:
            if "/page/2" in url:
                # page 2 触发 301 重定向（DLsite 实际行为：keyword 0 命中时 path 剥离）
                return _MockResponse(
                    301,
                    text="",
                    headers={"location": "/maniax/announce/list/day"},
                )
            # page 1 返 200 OK 但内容是全站新预告回退页（含 30 个伪候选 RJ）
            return _MockResponse(200, text=fake_recommended_rjcodes_html)
        # 第二个 template home-touch（如果走到这里就是 bug）
        if "home-touch/announce/list/day" in url:
            # home-touch 在 keyword 没命中时不返 redirect、直接 200 OK 全站新作页
            return _MockResponse(200, text=fake_recommended_rjcodes_html)
        return _MockResponse(404)

    mock_client = _MockHttpxClient(route_handler)

    async def fake_get_client() -> _MockHttpxClient:
        return mock_client

    monkeypatch.setattr(service.dlsite_service, "_get_client", fake_get_client)
    monkeypatch.setattr(
        service.dlsite_service,
        "_get_browser_headers",
        lambda: {"User-Agent": "test"},
    )

    found, failure_reason, _maker_hits = await service._search_dlsite_announce_works("いっしんふらん", max_pages=3)

    # ★ 核心不变量：redirect 触发后整函数返空，伪候选**绝不能**进入 found
    assert found == [], f"redirect 后竟然 commit 了 {len(found)} 个伪候选: {found[:5]}"
    # ★ 核心不变量：home-touch URL **绝不能**被请求（提前 abort 节省 HTTP）
    home_touch_calls = [url for url in mock_client.calls if "home-touch" in url]
    assert home_touch_calls == [], (
        f"home-touch template 不应该被尝试，实际跑了 {len(home_touch_calls)} 次: "
        f"{home_touch_calls[:3]}"
    )
    # 失败原因里必须含"重定向"，方便用户排错
    assert "重定向" in failure_reason or "redirect" in failure_reason.lower()


@pytest.mark.asyncio
async def test_announce_search_keeps_results_when_no_redirect(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没看到 redirect 的正常路径必须保留结果（不能被 abort 修复误伤）。"""
    legit_rjcodes_html = "".join(
        _work_card(rjcode, "RG12345", "常世常闇々")
        for rjcode in ["RJ01234567", "RJ01234568", "RJ01234569"]
    )

    def route_handler(url: str) -> _MockResponse:
        if "/maniax/announce/list/day/=/keyword/" in url:
            if "/page/2" in url or "/page/3" in url:
                # page 2/3 没有更多结果但也没 redirect（empty_streak 触发 break）
                return _MockResponse(200, text="无 RJ 的页面")
            # page 1 200 OK 抓到 3 个真 RJ
            return _MockResponse(200, text=legit_rjcodes_html)
        return _MockResponse(404)

    mock_client = _MockHttpxClient(route_handler)

    async def fake_get_client() -> _MockHttpxClient:
        return mock_client

    monkeypatch.setattr(service.dlsite_service, "_get_client", fake_get_client)
    monkeypatch.setattr(
        service.dlsite_service,
        "_get_browser_headers",
        lambda: {"User-Agent": "test"},
    )

    found, _failure_reason, maker_hits = await service._search_dlsite_announce_works("常世常闇々", max_pages=3)

    # 无 redirect 的合法路径，必须保留 page 1 命中的 3 个 RJ
    assert sorted(found) == ["RJ01234567", "RJ01234568", "RJ01234569"], (
        f"正常路径不应被新修复误伤，实际 found = {found}"
    )
    assert maker_hits == [{"maker_id": "RG12345", "maker_name": "常世常闇々"}]


@pytest.mark.asyncio
async def test_announce_search_first_template_failure_falls_back_to_second(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第一个 template 是非 redirect 的失败（如 5xx / 超时），仍然应该 fallback 到 home-touch。

    保证修复只针对"redirect 信号 = 强证明 keyword 0 命中"这种确定信号 abort，
    其他失败仍然有 backup 通道。
    """
    home_touch_rjcodes_html = "".join(
        _work_card(rjcode, "RG88888", "正常社团")
        for rjcode in ["RJ09999991", "RJ09999992"]
    )

    def route_handler(url: str) -> _MockResponse:
        if "/maniax/announce/list/day/=/keyword/" in url:
            # 第一个 template 全部 5xx（非 redirect 的失败）
            return _MockResponse(503, text="Service Unavailable")
        if "home-touch/announce/list/day" in url:
            if "page=2" in url or "page=3" in url:
                return _MockResponse(200, text="无 RJ 页")
            return _MockResponse(200, text=home_touch_rjcodes_html)
        return _MockResponse(404)

    mock_client = _MockHttpxClient(route_handler)

    async def fake_get_client() -> _MockHttpxClient:
        return mock_client

    monkeypatch.setattr(service.dlsite_service, "_get_client", fake_get_client)
    monkeypatch.setattr(
        service.dlsite_service,
        "_get_browser_headers",
        lambda: {"User-Agent": "test"},
    )

    found, _failure_reason, maker_hits = await service._search_dlsite_announce_works("正常社团", max_pages=3)

    # 第一个 template 5xx，第二个 template 应该被尝试且其结果保留
    assert sorted(found) == ["RJ09999991", "RJ09999992"], (
        f"非 redirect 的失败应该走 fallback，实际 found = {found}"
    )
    # 验证两个 template 都被请求过
    home_touch_calls = [url for url in mock_client.calls if "home-touch" in url]
    assert len(home_touch_calls) >= 1, "home-touch fallback 没有被尝试"
    assert maker_hits == [{"maker_id": "RG88888", "maker_name": "正常社团"}]


@pytest.mark.asyncio
async def test_announce_search_rejects_home_touch_default_page_after_primary_timeout(
    service: CircleCompletionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主入口超时后，即使 home-touch 返回全站作品，也不能产生社团候选。"""
    default_page = "".join(
        _work_card(f"RJ0167{n:04d}", "RG77777", "全站推荐社团") for n in range(0, 20)
    )

    def route_handler(url: str):
        if "/maniax/announce/list/day/=/keyword/" in url:
            return TimeoutError("request timed out")
        if "home-touch/announce/list/day" in url:
            return _MockResponse(200, text=default_page)
        return _MockResponse(404)

    mock_client = _MockHttpxClient(route_handler)

    async def fake_get_client() -> _MockHttpxClient:
        return mock_client

    monkeypatch.setattr(service.dlsite_service, "_get_client", fake_get_client)
    monkeypatch.setattr(service.dlsite_service, "_get_browser_headers", lambda: {"User-Agent": "test"})

    found, failure_reason, maker_hits = await service._search_dlsite_announce_works("おほ声の館", max_pages=3)

    assert found == []
    assert all(item["maker_id"] != "RG62099" for item in maker_hits)
    assert "timed out" in failure_reason
