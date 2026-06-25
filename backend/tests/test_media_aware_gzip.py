import asyncio

from app.api.routes import MediaAwareGZipMiddleware


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
