from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix='/api/browser-verification', tags=['browser-verification'])


async def validate_verification_url(url):
    from ..core.http_download_service import get_http_download_service
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not (parts.hostname or '').endswith('.imoutoheaven.org')
            or parts.username or parts.password):
        raise ValueError('YAAS 返回了非预期下载地址')
    await get_http_download_service().validate_url(url, allow_private_network=False)


@router.post('/task/{task_id}/open')
async def open_task(task_id: str):
    from ..core.task_engine import get_task_engine, TaskStatus, TaskType
    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task or task.type not in {TaskType.HTTP_DOWNLOAD, TaskType.RJ_SUBTITLE_FETCH}:
        raise HTTPException(404, detail='验证任务不存在')
    metadata = task.task_metadata or {}
    if task.status != TaskStatus.WAITING_MANUAL or not metadata.get('browser_verification_required'):
        raise HTTPException(409, detail='任务不在等待验证状态')
    url = metadata.get('browser_verification_url', '')
    try:
        resource_path = metadata.get('browser_verification_resource_path') or metadata.get('yaas_path') or ''
        if resource_path:
            from ..core.resource_source_service import get_resource_source_service
            data = await get_resource_source_service().request('get', {
                'path': resource_path, 'password': ''})
            url = str(data.get('raw_url') or '')
        await validate_verification_url(url)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(409, detail='无法刷新 YAAS 验证地址，请稍后重试') from exc
    return {'presentation': 'current_browser', 'verification_url': url}


@router.post('/task/{task_id}/handoff')
async def handoff_task(task_id: str):
    from ..core.task_engine import get_task_engine, TaskStatus, TaskType
    engine = get_task_engine()
    task = engine.get_task(task_id)
    if not task:
        return {'success': True}
    if task.type not in {TaskType.HTTP_DOWNLOAD, TaskType.RJ_SUBTITLE_FETCH}:
        raise HTTPException(404, detail='验证任务不存在')
    if (task.status != TaskStatus.WAITING_MANUAL
            or not (task.task_metadata or {}).get('browser_verification_required')
            or task_id in engine.processing):
        raise HTTPException(409, detail='任务状态已变化，不能清理')
    # 浏览器负责后续下载；只清理系统等待项，不记录下载或入库成功。
    try:
        removed = engine.remove_task(task_id)
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(409, detail='系统等待任务清理失败')
    return {'success': True}
