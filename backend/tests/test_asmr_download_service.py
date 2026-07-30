import os
from contextlib import asynccontextmanager

import aiohttp
import pytest

from app.core.asmr_download_service import (
    ASMR_DOWNLOAD_STREAM_CHUNK_BYTES,
    ASMR_PROBE_STATUS_MISSING,
    ASMR_PROBE_STATUS_UNAVAILABLE,
    ASMRDownloadService,
)


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


@pytest.mark.asyncio
async def test_download_file_resumes_same_partial_file_after_payload_disconnect(monkeypatch, tmp_path):
    service = ASMRDownloadService()
    target_path = tmp_path / "voice.wav"
    request_headers = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, *_args, **_kwargs):
            yield

    class BrokenContent:
        async def iter_chunked(self, _size):
            yield b"abc"
            raise aiohttp.ClientPayloadError("payload disconnected")

    class ResumeContent:
        async def iter_chunked(self, _size):
            yield b"def"

    class FakeResponse:
        def __init__(self, status, headers, content):
            self.status = status
            self.headers = headers
            self.content = content

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    responses = [
        FakeResponse(200, {"content-length": "6"}, BrokenContent()),
        FakeResponse(206, {"content-range": "bytes 3-5/6", "content-length": "3"}, ResumeContent()),
    ]

    class FakeSession:
        closed = False

        def get(self, *_args, **kwargs):
            request_headers.append(dict(kwargs.get("headers") or {}))
            return responses.pop(0)

    service._session = FakeSession()
    monkeypatch.setattr("app.core.asmr_download_service.get_resource_budget_service", lambda: Budget())
    monkeypatch.setattr("app.core.asmr_download_service.asyncio.sleep", lambda *_args: _no_wait())

    async def _run():
        return await service.download_file(
            "https://media.example.test/voice.wav",
            str(target_path),
            max_retries=2,
        )

    async def _no_wait():
        return None

    ok = await _run()

    assert ok is True
    assert target_path.read_bytes() == b"abcdef"
    assert "Range" not in request_headers[0]
    assert request_headers[1]["Range"] == "bytes=3-"
    assert not os.path.exists(str(target_path) + ".downloading")


@pytest.mark.asyncio
async def test_download_file_restarts_oversized_partial_after_http_416(monkeypatch, tmp_path):
    service = ASMRDownloadService()
    target_path = tmp_path / "voice.wav"
    partial_path = tmp_path / "voice.wav.downloading"
    partial_path.write_bytes(b"oversized")
    request_headers = []
    progress_rows = []

    class Budget:
        @asynccontextmanager
        async def acquire(self, *_args, **_kwargs):
            yield

    class EmptyContent:
        async def iter_chunked(self, _size):
            if False:
                yield b""

    class FullContent:
        async def iter_chunked(self, _size):
            yield b"abcdef"

    class FakeResponse:
        def __init__(self, status, headers, content):
            self.status = status
            self.headers = headers
            self.content = content

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    responses = [
        FakeResponse(416, {"content-range": "bytes */6"}, EmptyContent()),
        FakeResponse(200, {"content-length": "6"}, FullContent()),
    ]

    class FakeSession:
        closed = False

        def get(self, *_args, **kwargs):
            request_headers.append(dict(kwargs.get("headers") or {}))
            return responses.pop(0)

    async def _no_wait():
        return None

    service._session = FakeSession()
    monkeypatch.setattr("app.core.asmr_download_service.get_resource_budget_service", lambda: Budget())
    monkeypatch.setattr("app.core.asmr_download_service.asyncio.sleep", lambda *_args: _no_wait())

    ok = await service.download_file(
        "https://media.example.test/voice.wav",
        str(target_path),
        progress_callback=lambda downloaded, total: progress_rows.append((downloaded, total)),
        max_retries=2,
    )

    assert ok is True
    assert target_path.read_bytes() == b"abcdef"
    assert request_headers[0]["Range"] == "bytes=9-"
    assert "Range" not in request_headers[1]
    assert (0, 6) in progress_rows
    assert not partial_path.exists()


@pytest.mark.asyncio
async def test_fetch_work_info_short_circuits_after_api_failures():
    service = ASMRDownloadService()
    service.CIRCUIT_FAILURE_THRESHOLD = 2
    service.CIRCUIT_OPEN_SECONDS = 60
    calls = []

    class FakeResponse:
        status = 522

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, url, **_kwargs):
            calls.append(str(url))
            return FakeResponse()

    service._session = FakeSession()

    assert await service.fetch_work_info("RJ01000001") is None
    assert len(calls) == 2
    assert service._asmr_api_circuit_open() is True

    assert await service.fetch_work_info("RJ01000002") is None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fetch_work_info_with_status_distinguishes_transport_failure():
    service = ASMRDownloadService()
    calls = []

    class FakeResponse:
        status = 522

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, url, **_kwargs):
            calls.append(str(url))
            return FakeResponse()

    service._session = FakeSession()

    data, status = await service.fetch_work_info_with_status("RJ01000001")

    assert data is None
    assert status == ASMR_PROBE_STATUS_UNAVAILABLE
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fetch_work_info_with_status_marks_404_as_missing():
    service = ASMRDownloadService()
    calls = []

    class FakeResponse:
        status = 404

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, url, **_kwargs):
            calls.append(str(url))
            return FakeResponse()

    service._session = FakeSession()

    data, status = await service.fetch_work_info_with_status("RJ01000001")

    assert data is None
    assert status == ASMR_PROBE_STATUS_MISSING
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fetch_track_list_with_status_marks_empty_success_as_missing():
    service = ASMRDownloadService()

    class FakeResponse:
        status = 200

        async def json(self):
            return []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        closed = False

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    service._session = FakeSession()

    data, status = await service.fetch_track_list_with_status("RJ01000001")

    assert data == []
    assert status == ASMR_PROBE_STATUS_MISSING
