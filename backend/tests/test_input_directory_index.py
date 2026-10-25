import asyncio
import threading

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.input_directory_index import InputDirectoryIndex
from app.core.input_scan_discovery import InputScanDiscovery
from app.core.input_scan_repository import InputScanRepository
from app.models.database import InputScanDirectoryEntry


def test_spilled_prefix_paging_and_cleanup(db_session, db_engine, tmp_path):
    repository = InputScanRepository(sessionmaker(bind=db_engine))
    scan_id = repository.create_run(str(tmp_path), {})
    index = InputDirectoryIndex(repository, scan_id, str(tmp_path), memory_limit=3)
    for name in ["RJ_1.7z.001", "RJ_1.7z.002", "RJx1.7z.001", "other.zip"]:
        index.add(name)
    assert index.spilled and len(index.rows) <= 256
    assert sorted(index.members("rj_1")) == ["RJ_1.7z.001", "RJ_1.7z.002"]
    iterator = index.remaining()
    assert next(iterator) == ("RJ_1.7z.001", False)
    index.mark(["RJ_1.7z.001", "RJ_1.7z.002"])
    assert next(iterator) == ("RJ_1.7z.002", True)
    index.clear()
    with repository.session_factory() as db:
        assert db.query(InputScanDirectoryEntry).count() == 0


@pytest.mark.asyncio
async def test_first_single_does_not_wait_for_directory_close(tmp_path, monkeypatch):
    from app.core import input_scan_discovery as module

    (tmp_path / "first.7z").write_bytes(b"data")
    for number in range(200):
        (tmp_path / f"{number:03}.txt").write_bytes(b"text")
    original = module.os.scandir
    release = threading.Event()

    class Enumeration:
        def __enter__(self):
            with original(tmp_path) as entries:
                self.entries = sorted(entries, key=lambda entry: entry.name != "first.7z")
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            for number, entry in enumerate(self.entries):
                if number == 128:
                    assert release.wait(5)
                yield entry

    monkeypatch.setattr(module.os, "scandir", lambda path: Enumeration())
    discovery = InputScanDiscovery(str(tmp_path), capacity=1)
    await discovery.start()
    try:
        message = await asyncio.wait_for(discovery.receive(), 2)
        assert message["groups"][0]["source_path"] == str(tmp_path / "first.7z")
        assert not release.is_set()
    finally:
        release.set()
        await asyncio.wait_for(discovery.stop(), 3)
