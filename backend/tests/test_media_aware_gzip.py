import asyncio
import gzip
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import MediaAwareGZipMiddleware, PrecompressedStaticFiles


async def _sample_static_app(scope, receive, send):
    body = b"const value = '" + (b"x" * 4096) + b"';"
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/javascript"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _call_middleware(path: str):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    middleware = MediaAwareGZipMiddleware(_sample_static_app, minimum_size=1024)
    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [(b"accept-encoding", b"gzip, deflate, br")],
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    return headers, body.get("body", b"")


def test_assets_are_not_runtime_gzipped_even_when_client_accepts_gzip():
    headers, body = asyncio.run(_call_middleware("/assets/vendor.js"))

    assert "content-encoding" not in headers
    assert headers["content-length"] == str(len(body))
    assert body.startswith(b"const value = '")


def test_non_assets_keep_gzip_compression():
    headers, body = asyncio.run(_call_middleware("/api/example"))

    assert headers["content-encoding"] == "gzip"
    assert int(headers["content-length"]) == len(body)


def test_precompressed_static_files_serve_gzip_with_fixed_content_length(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    js_path = assets_dir / "vendor.js"
    js_body = b"const value = '" + (b"x" * 4096) + b"';"
    js_path.write_bytes(js_body)
    gz_path = Path(f"{js_path}.gz")
    gz_path.write_bytes(gzip.compress(js_body, compresslevel=9))

    app = FastAPI()
    app.mount("/assets", PrecompressedStaticFiles(directory=str(assets_dir)), name="assets")

    with TestClient(app) as client:
        response = client.get("/assets/vendor.js", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-length"] == str(os.stat(gz_path).st_size)
    assert response.headers["vary"] == "Accept-Encoding"
    assert "immutable" in response.headers["cache-control"]


def test_precompressed_static_files_respect_zero_quality_encoding(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    js_path = assets_dir / "vendor.js"
    js_body = b"const value = '" + (b"x" * 4096) + b"';"
    js_path.write_bytes(js_body)
    Path(f"{js_path}.gz").write_bytes(gzip.compress(js_body, compresslevel=9))

    app = FastAPI()
    app.mount("/assets", PrecompressedStaticFiles(directory=str(assets_dir)), name="assets")

    with TestClient(app) as client:
        response = client.get("/assets/vendor.js", headers={"Accept-Encoding": "gzip;q=0"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(js_body))
    assert response.headers["vary"] == "Accept-Encoding"
