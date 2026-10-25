"""文件移动设置工作台的只读接口。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config.settings import get_config
from ..core.file_move_diagnostics import journal_summary, probe_paths, runtime_status
from ..core.host_file_move_client import HostMoveError

router = APIRouter(prefix="/api/system/file-move", tags=["文件移动"])


class ProbeRequest(BaseModel):
    source: str
    destination: str


@router.get("/status")
def status():
    config = get_config()
    result = runtime_status(config)
    try:
        result["journal"] = journal_summary(config)
    except OSError as exc:
        result["journal"] = {"error": str(exc)}
    return result


@router.post("/probe")
def probe(request: ProbeRequest):
    try:
        return probe_paths(get_config(), request.source, request.destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HostMoveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
