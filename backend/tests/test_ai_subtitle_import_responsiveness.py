import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from app.core import ai_subtitle_match_service as module


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", [False, True])
async def test_slow_model_import_does_not_block_event_loop(monkeypatch, probe):
    service = module.AISubtitleMatchService()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    main_thread = threading.get_ident()
    import_threads = []
    fake_model = object()

    def slow_import(name):
        assert name == "litellm"
        import_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=2)
        return fake_model

    monkeypatch.setattr(module.importlib, "import_module", slow_import)
    streaming = AsyncMock(return_value=('{"matches":[]}', {}, True))
    completion = AsyncMock(return_value=("hi", {}))
    monkeypatch.setattr(service, "_complete_with_stream_preferred", streaming)
    monkeypatch.setattr(service, "_complete_non_streaming", completion)
    config = service._normalize_runtime_config({"model": "test-model", "api_key": "test-key"})
    coroutine = service._probe_model_connection(config) if probe else service._call_model(config, {})
    task = asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not task.done()
        assert len(import_threads) == 1 and import_threads[0] != main_thread
    finally:
        release.set()
        result = await task
    if probe:
        assert result["response_preview"] == "hi"
        assert completion.call_args.args[0] is fake_model
    else:
        assert result[0] == {"matches": []}
        assert streaming.call_args.args[0] is fake_model
