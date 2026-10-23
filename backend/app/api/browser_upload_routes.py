"""独立浏览器上传入口；沿用主应用安全网关，并要求会话能力令牌。"""
import asyncio
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
from ..core.browser_upload_service import get_browser_upload_service, UploadStopped
from ..core.browser_upload_storage import CHUNK_SIZE

router = APIRouter(prefix='/api/library/browser/uploads', tags=['库存浏览器上传'])


class CreateUpload(BaseModel):
    library_id: str = Field(max_length=100)
    target_path: str = Field(default='', max_length=4096)
    source_label: str = Field(default='电脑文件', max_length=500)


class ManifestEntry(BaseModel):
    relative_path: str = Field(max_length=4096)
    size: int = Field(default=0, ge=0, le=2**53 - 1)
    last_modified: int = Field(default=0, ge=0)
    is_directory: bool = False


class Manifest(BaseModel):
    entries: list[ManifestEntry] = Field(default_factory=list, max_length=100)
    finished: bool = False


class Action(BaseModel):
    action: Literal['pause', 'resume', 'cancel', 'retry', 'conflict', 'receive_failed', 'enumeration_failed']
    file_id: str | None = None
    decision: Literal['skip', 'replace', 'keep_both'] | None = None
    apply_all: bool = False
    reason: str | None = Field(default=None, max_length=2000)


def error(exc):
    code = 404 if isinstance(exc, KeyError) else 403 if isinstance(exc, PermissionError) else 409 if isinstance(exc, UploadStopped) else 507 if isinstance(exc, OSError) else 400
    return HTTPException(code, detail=str(exc))


def session(sid, token):
    try:
        service = get_browser_upload_service()
        return service, service.get(sid, token)
    except (KeyError, PermissionError) as exc:
        raise error(exc) from exc


def file_entry(state, fid):
    file = state['files'].get(fid)
    if file is None:
        raise HTTPException(404, detail='上传文件不存在')
    return file


@router.post('')
async def create(body: CreateUpload):
    try:
        return await get_browser_upload_service().create(**body.model_dump())
    except (ValueError, PermissionError, OSError) as exc:
        raise error(exc) from exc


@router.get('/{sid}')
async def status(sid: str, offset: int = 0, limit: int = 100, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(400, detail='分页参数无效')
    from itertools import islice
    return {**service.summary(state), 'revision': state.get('_revision', 0),
            'files': list(islice(state['files'].values(), offset, offset + limit))}


@router.post('/{sid}/manifest')
async def manifest(sid: str, body: Manifest, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    try:
        return {'files': await service.manifest(state, [e.model_dump() for e in body.entries], body.finished)}
    except (ValueError, PermissionError, UploadStopped, OSError) as exc:
        raise error(exc) from exc


@router.get('/{sid}/changes')
async def changes(sid: str, cursor: int = 0, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    updates = state.get('_changes', ())
    if updates and cursor and cursor < updates[0][0] - 1:
        raise HTTPException(409, detail='变更游标过期，请重新读取分页清单')
    page = [(rev, file) for rev, file in updates if rev > cursor][:200]
    return {**service.summary(state), 'files': [f for _, f in page],
            'cursor': page[-1][0] if page else state.get('_revision', 0),
            'has_more': bool(page and page[-1][0] < state.get('_revision', 0))}


@router.put('/{sid}/files/{fid}/chunks')
async def chunk(sid: str, fid: str, request: Request, offset: int,
                x_chunk_sha256: str = Header(), x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    file = file_entry(state, fid)
    try:
        if file['status'] != 'completed':
            service.active(state)
        async with service.receive_slots:
            data = bytearray()
            async for block in request.stream():
                if file['status'] != 'completed':
                    service.active(state)
                if len(data) + len(block) > CHUNK_SIZE:
                    raise HTTPException(413, detail='分块超过 8 MiB')
                data.extend(block)
            return await service.chunk(state, file, offset, data, x_chunk_sha256)
    except (ValueError, PermissionError, UploadStopped, OSError) as exc:
        file.update(reason=str(exc), stage='上传接收', retryable=True)
        raise error(exc) from exc


@router.get('/{sid}/files/{fid}/checkpoint')
async def checkpoint(sid: str, fid: str, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    return await service.checkpoint(state, file_entry(state, fid))


@router.post('/{sid}/files/{fid}/complete')
async def complete(sid: str, fid: str, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    try:
        return await service.complete_file(state, file_entry(state, fid))
    except (ValueError, UploadStopped, OSError) as exc:
        raise error(exc) from exc


@router.post('/{sid}/actions')
async def action(sid: str, body: Action, x_upload_token: str = Header(default='')):
    service, state = session(sid, x_upload_token)
    try:
        return await service.action(state, **body.model_dump())
    except (ValueError, UploadStopped, OSError) as exc:
        raise error(exc) from exc
