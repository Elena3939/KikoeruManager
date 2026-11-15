"""在专用 *_test 数据库测量整表导入，禁止连接业务数据库。"""
import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def peak_memory():
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def main():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from app.models.database import Base
    from app.core import link_sheet_service as service_module
    from app.core.circle_completion_changes import ENQUEUE_SQL
    from app.api import link_sheet_routes
    from fastapi import FastAPI
    import httpx
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    url = os.environ.get("KIKOERUMANAGER_TEST_DATABASE_URL", "")
    if not url or not (make_url(url).database or "").endswith("_test"):
        raise SystemExit("仅允许 KIKOERUMANAGER_TEST_DATABASE_URL 指向 *_test 数据库")
    database = create_engine(url)
    with database.begin() as db:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(database)
    with database.begin() as db:
        db.execute(text(ENQUEUE_SQL))
    service_module.SessionLocal = sessionmaker(bind=database)
    service_module.engine = database
    service_module.broadcast = lambda: None
    service = service_module.LinkSheetService()

    def size():
        with database.connect() as db:
            return db.scalar(text("""
                SELECT COALESCE(sum(pg_total_relation_size(oid)),0) FROM pg_class
                WHERE relnamespace='public'::regnamespace AND relname LIKE 'link_sheet_%'
                  AND relkind='r'
            """))
    before = size()
    with tempfile.TemporaryDirectory(prefix="link-sheet-benchmark-") as directory:
        service_module.upload_path = lambda bid: Path(directory) / f"{bid}.xlsx"
        link_sheet_routes.upload_path = service_module.upload_path
        link_sheet_routes.get_link_sheet_service = lambda: service
        application = FastAPI()
        application.include_router(link_sheet_routes.router)

        async def upload():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                         base_url="http://test") as client:
                with args.workbook.open("rb") as stream:
                    response = await client.post("/api/link-sheet/imports",
                        files={"file": (args.workbook.name, stream)})
                response.raise_for_status()
                return response.json()["id"]

        results = []
        for iteration in range(2):
            upload_started = time.monotonic()
            batch_id = asyncio.run(upload())
            started = time.monotonic()
            service._tick()
            parsed = time.monotonic()
            result = service.confirm(batch_id)
            results.append({"iteration": iteration + 1, "statistics": result["statistics"],
                            "upload_bytes": args.workbook.stat().st_size,
                            "upload_seconds": round(started - upload_started, 3),
                            "parse_seconds": round(parsed - started, 3),
                            "publish_seconds": round(time.monotonic() - parsed, 3),
                            "table_and_index_bytes": int(size() - before)})
        print(json.dumps({"runs": results, "peak_process_memory_bytes": peak_memory()}, ensure_ascii=False))
    database.dispose()


if __name__ == "__main__":
    main()
