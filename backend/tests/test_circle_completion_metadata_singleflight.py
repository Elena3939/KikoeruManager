"""``_fetch_metadata_dict`` 单飞锁回归测试。

背景：322 件作品社团索引的 ``stage_prepare_candidates`` 阶段实测耗时 16 分钟，
root cause 是 278 个 candidate 并发 await 同一个 ~150 个 canonical 的 metadata：

- in-memory ``_metadata_cache`` 在首个 task 完成 set 之前会被所有 task 同时 miss
- 每个 task 又各自打 DB + ``metadata_service.fetch``（DLsite ``product/info/ajax``）
- 实际产生 278 次重复 HTTP（**惊群**），即使理论上只需要 ~150 次

修复：``self._metadata_inflight: Dict[str, asyncio.Future]``。同一 RJ 同时只允许
**首个** task 跑真实 fetch，其他 task 全部 ``await`` 共享同一份 Future。

本测试覆盖：

- 并发 N 次调 ``_fetch_metadata_dict(rj)`` 时，``metadata_service.fetch`` 只跑一次
- 所有 N 个调用返回值相同（来自同一份 Future.set_result）
- inflight Future 完成后立刻被清出字典，不泄漏
- ``refresh=True`` 显式绕过单飞（用户主动刷新需要触网）
- 抛异常时 inflight 不会泄漏

这些是 ``stage_prepare_candidates`` 16 → 2 分钟优化的核心契约。任何改动让
"惊群下重复打 HTTP"再次出现的回归都会让索引重新慢回 40 分钟，**没有这些测试很难发现**。
"""

import asyncio

import pytest

from app.core.circle_completion_service import CircleCompletionService


@pytest.fixture
def service(monkeypatch):
    svc = CircleCompletionService()
    # 不动 _metadata_cache TTL，让单飞测试条件保持真实。
    svc._metadata_cache.clear()
    svc._metadata_inflight.clear()
    return svc


@pytest.mark.asyncio
async def test_metadata_singleflight_collapses_concurrent_calls(service, monkeypatch):
    """并发 50 次调同一 RJ 时，metadata_service.fetch 只被打 1 次。"""

    fetch_calls = 0
    fetch_in_flight = 0
    fetch_max_concurrent = 0

    async def fake_fetch(rj, task, force_refresh=False):
        nonlocal fetch_calls, fetch_in_flight, fetch_max_concurrent
        fetch_calls += 1
        fetch_in_flight += 1
        fetch_max_concurrent = max(fetch_max_concurrent, fetch_in_flight)
        try:
            # 模拟一次较慢的 DLsite HTTP，让并发 await 真正堆起来
            await asyncio.sleep(0.05)
            return {"rjcode": rj, "work_name": f"Title for {rj}", "maker_name": "Test Circle"}
        finally:
            fetch_in_flight -= 1

    monkeypatch.setattr(service.metadata_service, "fetch", fake_fetch)
    # 跳过 DB 查询路径，强制走 metadata_service.fetch
    monkeypatch.setattr(
        "app.core.circle_completion_service.SessionLocal",
        lambda: _DummySession(),
    )

    rj = "RJ01234567"
    results = await asyncio.gather(
        *[service._fetch_metadata_dict(rj) for _ in range(50)]
    )

    assert fetch_calls == 1, (
        f"单飞失败：50 并发 await 应该只触发 1 次 metadata fetch，"
        f"实际触发了 {fetch_calls} 次。这意味着惊群效应回来了，"
        f"``stage_prepare_candidates`` 会再次慢回 16 分钟。"
    )
    assert fetch_max_concurrent == 1
    # 所有调用返回同一份 payload
    for payload in results:
        assert payload["rjcode"] == rj
        assert payload["work_name"] == f"Title for {rj}"
    # inflight 完成后立刻清出
    assert rj not in service._metadata_inflight


@pytest.mark.asyncio
async def test_metadata_singleflight_does_not_leak_inflight_on_exception(service, monkeypatch):
    """fetch 抛异常时 inflight 必须清出，否则同一 RJ 后续永久卡 `await existing`。"""

    async def boom(rj, task, force_refresh=False):
        await asyncio.sleep(0.01)
        raise RuntimeError("simulated DLsite 500")

    monkeypatch.setattr(service.metadata_service, "fetch", boom)
    monkeypatch.setattr(
        "app.core.circle_completion_service.SessionLocal",
        lambda: _DummySession(),
    )

    rj = "RJ01111111"
    # 一组并发请求都会拿到同样的异常（共享 Future）
    with pytest.raises(RuntimeError, match="simulated DLsite 500"):
        await asyncio.gather(
            *[service._fetch_metadata_dict(rj) for _ in range(5)],
            return_exceptions=False,
        )
    # 关键：inflight 字典必须空，否则后续重试永远 await 旧的 Future
    assert rj not in service._metadata_inflight


@pytest.mark.asyncio
async def test_metadata_singleflight_refresh_true_bypasses_inflight(service, monkeypatch):
    """``refresh=True`` 跳过 inflight 复用 —— 强制每次都触网。

    这是用户在"主动刷新"路径上的合约：refresh=True 时即使 inflight 有进行中的
    task，调用方仍然要拿到最新结果。这里只验证 refresh=True 不读 inflight；
    实际并发 refresh 的行为是"各自跑"，不属于单飞优化目标。
    """

    fetch_call_log = []

    async def fake_fetch(rj, task, force_refresh=False):
        fetch_call_log.append({"rj": rj, "refresh": force_refresh})
        return {"rjcode": rj, "work_name": "fresh"}

    monkeypatch.setattr(service.metadata_service, "fetch", fake_fetch)
    monkeypatch.setattr(
        "app.core.circle_completion_service.SessionLocal",
        lambda: _DummySession(),
    )

    rj = "RJ02222222"
    # 第一次 refresh=False：写 cache
    payload1 = await service._fetch_metadata_dict(rj, refresh=False)
    assert payload1["work_name"] == "fresh"

    # refresh=True：必须触网，不能直接 return cache
    payload2 = await service._fetch_metadata_dict(rj, refresh=True)
    assert payload2["work_name"] == "fresh"

    assert len(fetch_call_log) == 2
    assert fetch_call_log[1]["refresh"] is True


class _DummySession:
    """避开真实 DB 查询路径的测试桩。"""

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def close(self):
        pass
