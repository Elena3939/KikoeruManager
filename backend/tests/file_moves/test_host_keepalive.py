"""宿主排队、心跳与取消确认的回归测试。"""
import importlib
import io
import socket
import socketserver
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from app.core.file_move_protocol import VERSION, encode
from app.core.host_file_move_client import HostMoveClient, HostMoveError


@pytest.fixture
def host(monkeypatch):
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace())
        monkeypatch.setattr(socketserver, "ThreadingUnixStreamServer", socketserver.ThreadingTCPServer, raising=False)
    module = importlib.import_module("app.core.host_file_mover")
    return module


def test_cancel_before_prepare_is_durable(host, tmp_path):
    executor = host.Executor({"mappings": [], "records": str(tmp_path)})
    operation_id = "12345678-1234-1234-1234-123456789abc"
    assert executor.control({"action": "cancel", "operation_id": operation_id}) == {"state": "cancelled"}
    restarted = host.Executor({"mappings": [], "records": str(tmp_path)})
    with pytest.raises(RuntimeError, match="已终止"):
        restarted.prepare({"operation_id": operation_id, "mapping_version": restarted.mapping_version,
                           "source": "/a", "destination": "/b", "source_identity": {}})


def test_control_bypasses_execution_queue_and_keeps_heartbeat(host):
    handler = host.Handler.__new__(host.Handler)
    handler.heartbeat_seconds = 0.01
    handler.wfile = io.BytesIO()
    slots = threading.BoundedSemaphore(1)
    slots.acquire()

    def dispatch(request):
        time.sleep(0.035)
        return {"state": "cancelled"}

    handler.server = SimpleNamespace(slots=slots, executor=SimpleNamespace(dispatch=dispatch))
    try:
        result = handler.dispatch_with_keepalive({"action": "cancel"})
        assert result == {"state": "cancelled"}
        assert b'"pending":true' in handler.wfile.getvalue()
    finally:
        slots.release()


def test_queued_prepare_sends_heartbeat(host):
    handler = host.Handler.__new__(host.Handler)
    handler.heartbeat_seconds = 0.01
    handler.wfile = io.BytesIO()
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    handler.server = SimpleNamespace(slots=slots, executor=SimpleNamespace(dispatch=lambda request: {"state": "ready"}))
    timer = threading.Timer(0.04, slots.release)
    timer.start()
    try:
        assert handler.dispatch_with_keepalive({"action": "prepare"}) == {"state": "ready"}
        assert b'"pending":true' in handler.wfile.getvalue()
    finally:
        timer.join()


def test_connection_limit_rejects_without_blocking_accept(host):
    server = host.Server.__new__(host.Server)
    server.connections = threading.BoundedSemaphore(1)
    server.connections.acquire()
    rejected = []
    server.shutdown_request = rejected.append
    request = object()
    server.process_request(request, None)
    assert rejected == [request]
    server.connections.release()


def test_cancel_checkpoint_never_publishes_clone(monkeypatch, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"keep")
    client = HostMoveClient("test")
    calls = []

    def checkpoint():
        if calls:
            raise RuntimeError("取消任务")

    def request(action, checkpoint=None, **payload):
        calls.append(action)
        if checkpoint:
            checkpoint()
        return {"state": "cancelled"}

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(RuntimeError, match="取消任务"):
        client.clone(str(source), str(target), "mapping", checkpoint)
    assert calls == ["prepare", "cancel"]
    assert source.read_bytes() == b"keep"
    assert not target.exists()


@pytest.mark.parametrize("heartbeat", [True, False])
def test_client_timeout_means_no_response_not_total_duration(monkeypatch, heartbeat):
    original_socket = socket.socket
    monkeypatch.setattr(socket, "AF_UNIX", socket.AF_INET, raising=False)
    listener = original_socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    address = listener.getsockname()

    def serve():
        with listener:
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                try:
                    for _ in range(8):
                        time.sleep(0.02)
                        if heartbeat:
                            connection.sendall(encode({"version": VERSION, "pending": True}))
                    connection.sendall(encode({"version": VERSION, "ok": True, "result": {"state": "ready"}}))
                except OSError:
                    pass

    class RedirectSocket(original_socket):
        def __init__(self, *_args, fileno=None):
            super().__init__(socket.AF_INET, socket.SOCK_STREAM, fileno=fileno)

        def connect(self, _path):
            return super().connect(address)

    worker = threading.Thread(target=serve)
    worker.start()
    monkeypatch.setattr(socket, "socket", RedirectSocket)
    checkpoints = []
    try:
        client = HostMoveClient("test", timeout=0.1)
        if heartbeat:
            assert client.request("prepare", checkpoint=lambda: checkpoints.append(1)) == {"state": "ready"}
            assert len(checkpoints) == 8
        else:
            with pytest.raises(HostMoveError):
                client.request("prepare")
    finally:
        worker.join(timeout=2)
        assert not worker.is_alive()
