"""链接库接口只返回固定引用与脱敏文件信息。"""
import asyncio
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from pydantic import BaseModel

from ..core.link_sheet_service import get_link_sheet_service, upload_path

router = APIRouter(prefix="/api/link-sheet", tags=["link-sheet"])
MAX_UPLOAD = 100 * 1024 * 1024


async def call(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/imports")
async def upload(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="请选择 .xlsx 文件")
    batch_id = uuid.uuid4().hex
    path = upload_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(status_code=413, detail="Excel 超过 100 MiB")
                sha.update(chunk)
                await asyncio.to_thread(output.write, chunk)
        await call(get_link_sheet_service().create_import, batch_id,
                   Path(file.filename.replace("\\", "/")).name, sha.hexdigest())
        return {"id": batch_id, "status": "queued"}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/imports")
async def history(page: int = Query(1, ge=1)):
    return await call(get_link_sheet_service().history, page)


@router.get("/imports/{batch_id}")
async def status(batch_id: str):
    return await call(get_link_sheet_service().batch, batch_id)


@router.post("/imports/{batch_id}/confirm")
async def confirm(batch_id: str):
    return await call(get_link_sheet_service().confirm, batch_id)


@router.post("/imports/{batch_id}/cancel")
async def cancel(batch_id: str):
    await call(get_link_sheet_service().cancel, batch_id)
    return {"ok": True}


@router.get("/works")
async def works(page: int = Query(1, ge=1), search: str = Query("", max_length=200),
                batch_id: str = "", errors_only: bool = False,
                page_size: int = Query(10, ge=1, le=100)):
    return await call(get_link_sheet_service().works, page, search, batch_id, errors_only, page_size)


@router.get("/revisions/{revision_id}")
async def detail(revision_id: str):
    return await call(get_link_sheet_service().detail, revision_id)


@router.post("/revisions/{revision_id}/download")
async def download(revision_id: str, group_id: str = Query("")):
    return {"tasks": await get_link_sheet_service().download_revision(revision_id, group_id)}


class EnabledRequest(BaseModel):
    enabled: bool


@router.patch("/works/{rjcode}")
async def enabled(rjcode: str, payload: EnabledRequest):
    await call(get_link_sheet_service().set_enabled, rjcode, payload.enabled)
    return {"ok": True}
