import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.api_rename_planning import get_api_rename_plan_semaphore
from app.core.dlsite_service import DLsiteApiService
from app.core.metadata_service import MetadataService, WorkMetadata
from app.core.rename_service import RenameService


@pytest.mark.asyncio
async def test_japanese_metadata_failure_can_retry_in_same_rename_service(monkeypatch):
    fetch = AsyncMock(side_effect=[None, {"maker_name": "原社团"}])
    monkeypatch.setattr(MetadataService, "fetch_japanese_metadata", fetch)
    service = RenameService()
    assert await service._get_japanese_metadata("RJ01730110") is None
    assert await service._get_japanese_metadata("RJ01730110") == {"maker_name": "原社团"}
    assert await service._get_japanese_metadata("RJ01730110") == {"maker_name": "原社团"}
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_batch_api_rename_queries_both_languages_concurrently(monkeypatch):
    from app.api import routes

    primary_started = asyncio.Event()
    japanese_started = asyncio.Event()
    name = "RJ01730110"
    library = SimpleNamespace(id="rename-parallel-test", type="synology_filestation")
    manager = SimpleNamespace(
        get_library_definition=lambda _id: library,
        _resolve_remote_operation_path=lambda _library, path, **_kwargs: path,
    )

    async def primary(_self, _path, _task, *, force_refresh=False):
        assert force_refresh is True
        primary_started.set()
        await asyncio.wait_for(japanese_started.wait(), timeout=1)
        return {"rjcode": name, "work_name": "作品", "maker_name": "原社团",
                "metadata_evidence_source": "dlsite_product"}

    async def japanese(_self, _rjcode, *, force_refresh=False):
        assert force_refresh is True
        japanese_started.set()
        await asyncio.wait_for(primary_started.wait(), timeout=1)
        return {"maker_name": "原社团"}

    monkeypatch.setattr(routes, "get_library_manager", lambda: manager)
    monkeypatch.setattr(routes, "get_config", lambda: SimpleNamespace(
        rename=SimpleNamespace(use_japanese_metadata=True),
    ))
    monkeypatch.setattr(MetadataService, "fetch", primary)
    monkeypatch.setattr(RenameService, "_get_japanese_metadata", japanese)
    monkeypatch.setattr(RenameService, "_compile_name", lambda *_args: name)
    monkeypatch.setattr("app.core.activity_log_service.log_api_rename_action", lambda **_kwargs: None)
    monkeypatch.setattr("app.core.activity_log_service.log_batch_api_rename_result", lambda **_kwargs: None)
    record_failure = AsyncMock()
    # 成功且名称未变时不应创建问题记录或执行文件操作。
    monkeypatch.setattr("app.core.api_rename_failure_service.record_api_rename_failure", record_failure)
    request = SimpleNamespace(headers={}, json=AsyncMock(return_value={
        "library_id": library.id, "paths": [f"/library/{name}"],
    }))
    result = await asyncio.wait_for(routes.batch_api_rename_library_items(request, None), timeout=3)
    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_unverified_product_cache_is_refreshed_once(monkeypatch):
    fresh = {"metadata_verification_status": "verified", "product": {"workno": "RJ01730110"}}
    api = SimpleNamespace(get_product_info=AsyncMock(side_effect=[
        {"metadata_verification_status": "unverified"}, fresh,
    ]))
    monkeypatch.setattr("app.core.metadata_service.get_dlsite_service", lambda: api)
    result = await MetadataService()._get_product_info_for_metadata("RJ01730110")
    assert result is fresh
    assert [call.kwargs["refresh"] for call in api.get_product_info.await_args_list] == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_japanese_metadata_accepts_only_verified_shared_product(monkeypatch, verified):
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: SimpleNamespace(
        metadata=SimpleNamespace(sleep_interval=0),
    ))
    service = MetadataService()
    fetch = AsyncMock(return_value={
        "metadata_verification_status": "verified" if verified else "unverified",
        "product": {"workno": "RJ01730110", "work_name": "作品", "maker_name": "原社团",
                    "translation_info": {"is_original": True}},
    })
    monkeypatch.setattr(service, "_get_product_info_for_metadata", fetch)
    result = await service.fetch_japanese_metadata("RJ01730110")
    if verified:
        assert result["maker_name"] == "原社团"
    else:
        assert result is None
    assert fetch.await_args.kwargs["locale"] == "ja-JP"


@pytest.mark.asyncio
async def test_primary_metadata_keeps_specific_evidence(monkeypatch):
    service = MetadataService()
    monkeypatch.setattr("app.core.metadata_service.get_config", lambda: SimpleNamespace(
        metadata=SimpleNamespace(sleep_interval=0, locale="zh_cn"),
    ))
    monkeypatch.setattr(service, "_get_product_info_for_metadata", AsyncMock(return_value={
        "product": {"workno": "RJ01730110"}, "fallback_used": True,
        "fallback_source": "page_metadata_unverified",
        "metadata_evidence_source": "page_embedded_product",
        "metadata_verification_status": "verified",
    }))
    monkeypatch.setattr(service, "_build_metadata_from_dlsite_product", AsyncMock(return_value=WorkMetadata()))
    result = await service._fetch_from_dlsite_product_info("RJ01730110")
    assert result.metadata_evidence_source == "page_embedded_product"


@pytest.mark.asyncio
async def test_japanese_manual_refresh_bypasses_both_cache_layers(monkeypatch):
    service = RenameService()
    service._japanese_metadata_cache['RJ01056661'] = {'cvs': []}
    metadata = MetadataService()
    monkeypatch.setattr('app.core.metadata_service.get_config', lambda: SimpleNamespace(
        metadata=SimpleNamespace(sleep_interval=0),
    ))
    fetch = AsyncMock(return_value={
        'metadata_verification_status': 'verified',
        'product': {'workno': 'RJ01056661', 'maker_name': '原社团',
                    'translation_info': {'is_original': True},
                    'creaters': {'voice_by': [{'name': '秋野かえで'}]}},
    })
    monkeypatch.setattr(metadata, '_get_product_info_for_metadata', fetch)
    monkeypatch.setattr(metadata, '_resolve_original_maker_fields', AsyncMock(return_value={}))
    monkeypatch.setattr('app.core.metadata_service.MetadataService', lambda: metadata)
    result = await service._get_japanese_metadata('RJ01056661', force_refresh=True)
    assert result['cvs'] == ['秋野かえで']
    assert fetch.await_args.kwargs['refresh'] is True


@pytest.mark.parametrize('notice', [
    'お住いの国・地域からは本作品は購入できません。',
    '<title>メンテナンスのお知らせ</title>',
])
def test_restricted_pages_cannot_be_verified_by_embedded_identity(notice):
    service = DLsiteApiService()
    identity = '''<meta property="og:title" content="真实作品标题">
    <script>var contents = {"detail":[{
        "id":"RJ01056661","name":"真实作品标题","brand":"RG33577"
    }]};</script>'''
    html = notice + identity
    assert service._parse_product_from_html('RJ01056661', 'url', 'url', identity) is not None
    assert service._is_unavailable_product_page(html)
    assert service._parse_product_from_html('RJ01056661', 'url', 'url', html) is None


@pytest.mark.asyncio
async def test_refresh_removes_old_product_html_and_relation_caches(monkeypatch):
    service = DLsiteApiService()
    code = 'RJ01056661'
    old_keys = [
        f'product_info:{code}:ja-JP',
        f'page_html_raw:https://www.dlsite.com/maniax/work/=/product_id/{code}.html',
        f'page_metadata:https://www.dlsite.com/maniax/work/=/product_id/{code}.html',
        f'linked_works:{code}',
    ]
    for key in old_keys:
        service.cache[key] = {'data': {'creaters': {}}, 'timestamp': datetime.now()}
    service.cache['unrelated'] = {'data': '保留'}
    service._translation_info_cache[code] = ('旧关联', datetime.now())

    async def fresh_product(*_args, **_kwargs):
        assert all(key not in service.cache for key in old_keys)
        assert code not in service._translation_info_cache
        assert service.cache['unrelated']['data'] == '保留'
        return {'workno': code, 'maker_name': '原社团',
                'creaters': {'voice_by': [{'name': '秋野かえで'}]}}

    monkeypatch.setattr(service, '_fetch_product_payload', fresh_product)
    result = await service.get_product_info(code, locale='ja-JP', refresh=True)
    assert result['product']['creaters']['voice_by'] == [{'name': '秋野かえで'}]


@pytest.mark.asyncio
async def test_page_selection_prefers_verified_evidence(monkeypatch):
    service = DLsiteApiService()
    monkeypatch.setattr(service, "_fetch_page_html_with_url", AsyncMock(return_value=("html", "url")))
    def parse(rj, url, *_args):
        return {"workno": rj, "maker_name": "原社团", "metadata_evidence_source": (
            "page_embedded_product" if "/announce/" in url else "page_metadata_unverified"
        )}
    monkeypatch.setattr(service, "_parse_product_from_html", parse)
    result = await service._fetch_product_page_metadata("RJ01730110")
    assert result["metadata_evidence_source"] == "page_embedded_product"


@pytest.mark.asyncio
async def test_failed_html_is_retried_without_refresh(monkeypatch):
    service = DLsiteApiService()
    url = 'https://www.dlsite.com/maniax/work/=/product_id/RJ01056661.html'
    key = f'page_html_raw:{url}'
    service.cache[key] = {'data': '', 'timestamp': datetime.now()}
    response = SimpleNamespace(text='<html>正常详情</html>', url=url, raise_for_status=lambda: None)
    fetch = AsyncMock(side_effect=[RuntimeError('临时网络错误'), response])
    monkeypatch.setattr(service, '_guarded_get', fetch)
    assert await service._fetch_page_html_with_url(url) == ('', url)
    assert key not in service.cache
    assert await service._fetch_page_html_with_url(url) == (response.text, url)
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_failed_product_cache_does_not_block_recovery(monkeypatch):
    service = DLsiteApiService()
    code = 'RJ01056661'
    key = f'product_info:{code}:'
    service.cache[key] = {'data': None, 'timestamp': datetime.now(), 'ttl_seconds': 300}
    fetch = AsyncMock(side_effect=[None, {
        'workno': code, 'work_name': '作品', 'maker_name': '社团',
        'creaters': {'voice_by': [{'name': '秋野かえで'}]},
    }])
    monkeypatch.setattr(service, '_fetch_product_payload', fetch)
    monkeypatch.setattr(service, '_resolve_translation_page_fallback', AsyncMock(return_value={}))
    monkeypatch.setattr(service, '_fetch_product_page_metadata', AsyncMock(return_value=None))
    assert await service.get_product_info(code) is None
    assert key not in service.cache
    recovered = await service.get_product_info(code)
    assert recovered['product']['creaters']['voice_by'][0]['name'] == '秋野かえで'
    assert fetch.await_count == 2
    assert await service.get_product_info(code) == recovered
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_batches_share_six_plan_slots():
    gate = get_api_rename_plan_semaphore()
    assert get_api_rename_plan_semaphore() is gate
    active = peak = 0
    release = asyncio.Event()
    filled = asyncio.Event()
    async def plan():
        nonlocal active, peak
        async with get_api_rename_plan_semaphore():
            active += 1
            peak = max(active, peak)
            if active == 6:
                filled.set()
            await release.wait()
            active -= 1
    tasks = [asyncio.create_task(plan()) for _ in range(12)]
    try:
        await asyncio.wait_for(filled.wait(), timeout=1)
        assert active == 6
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert peak == 6
