import os
from contextlib import asynccontextmanager

import pytest

from app.core.asmr_download_service import ASMR_DOWNLOAD_STREAM_CHUNK_BYTES, ASMRDownloadService


@pytest.mark.asyncio
async def test_download_file_uses_large_stream_chunk_and_reports_progress(tmp_path):
    service = ASMRDownloadService()
    target_path = tmp_path / "voice.wav"
    seen_chunk_sizes = []
    progress_rows = []

    class FakeContent:
        async def iter_chunked(self, size):
            seen_chunk_sizes.append(size)
            yield b"abc"
            yield b"def"

    class FakeResponse:
        status = 200
        headers = {"content-length": "6"}

        def __init__(self):
            self.content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    service._session = FakeSession()

    ok = await service.download_file(
        "https://media.example.test/voice.wav",
        str(target_path),
        progress_callback=lambda downloaded, total: progress_rows.append((downloaded, total)),
        max_retries=1,
    )

    assert ok is True
    assert target_path.read_bytes() == b"abcdef"
    assert seen_chunk_sizes == [ASMR_DOWNLOAD_STREAM_CHUNK_BYTES]
    assert progress_rows[-1] == (6, 6)
    assert not os.path.exists(str(target_path) + ".downloading")


@pytest.mark.asyncio
async def test_download_file_uses_network_download_budget(monkeypatch, tmp_path):
    service = ASMRDownloadService()
    target_path = tmp_path / "voice.wav"
    calls = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    class FakeContent:
        async def iter_chunked(self, _size):
            yield b"abc"

    class FakeResponse:
        status = 200
        headers = {"content-length": "3"}

        def __init__(self):
            self.content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    service._session = FakeSession()
    monkeypatch.setattr("app.core.asmr_download_service.get_resource_budget_service", lambda: Budget())

    ok = await service.download_file(
        "https://media.example.test/voice.wav",
        str(target_path),
        max_retries=1,
    )

    assert ok is True
    assert calls == [("network_download", 1, "asmr.download_file")]
