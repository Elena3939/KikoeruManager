"""页面 404 只保留一条作品级汇总，失败状态不能污染后续成功请求。"""
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.dlsite_service import DLsiteApiService


@pytest.mark.asyncio
async def test_expected_404_has_one_summary_and_can_recover(monkeypatch, caplog):
    service = DLsiteApiService()
    caplog.set_level(logging.DEBUG, logger='app.core.dlsite_service')
    async def missing(url, **kwargs):
        return httpx.Response(404, request=httpx.Request('GET', url))
    monkeypatch.setattr(service, '_guarded_get', missing)
    monkeypatch.setattr(service, '_fetch_product_payload', AsyncMock(return_value=None))
    assert not await service._is_public_work_available('RJ01234567')
    summaries = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert len(summaries) == 1
    assert 'work/announce 404' in summaries[0].getMessage()
    assert not summaries[0].exc_info
    url = service._build_product_page_url('RJ01234567')
    async def recovered(url, **kwargs):
        return httpx.Response(200, text='<html>恢复页面</html>', request=httpx.Request('GET', url))
    monkeypatch.setattr(service, '_guarded_get', recovered)
    assert (await service._fetch_page_html_with_url(url))[0] == '<html>恢复页面</html>'
    assert f'page_html_status:{url}' not in service.cache
