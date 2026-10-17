"""通过本地假代理验证真实 CONNECT / SOCKS5 握手及 IMAP 连接。"""

import base64
import builtins
import socket
import threading
from unittest.mock import patch

import pytest

from app.core.imap_proxy import _create_proxy_socket, create_imap_client, parse_proxy_url


@pytest.fixture(autouse=True)
def without_pysocks(monkeypatch):
    """模拟生产环境：明确禁止导入 PySocks，防止本机安装掩盖依赖问题。"""
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "socks":
            raise ModuleNotFoundError("生产环境没有 PySocks")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.mark.parametrize("scheme", ["http", "socks5h"])
@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("reply_type", [1, 3, 4])
def test_proxy_tunnel_and_remote_dns(scheme, authenticated, reply_type):
    errors = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)

    def serve():
        try:
            with listener, listener.accept()[0] as conn:
                conn.settimeout(5)
                stream = conn.makefile("rb")
                if scheme == "http":
                    headers = []
                    while line := stream.readline():
                        headers.append(line)
                        if line == b"\r\n":
                            break
                    assert headers[0] == b"CONNECT imap.invalid:993 HTTP/1.1\r\n"
                    auth_header = b"Proxy-Authorization: Basic " + base64.b64encode(b"user:p@ss") + b"\r\n"
                    assert (auth_header in headers) is authenticated
                    conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                else:
                    method = b"\x02" if authenticated else b"\x00"
                    assert stream.read(3) == b"\x05\x01" + method
                    conn.sendall(b"\x05" + method)
                    if authenticated:
                        assert stream.read(1) == b"\x01"
                        assert stream.read(stream.read(1)[0]) == b"user"
                        assert stream.read(stream.read(1)[0]) == b"p@ss"
                        conn.sendall(b"\x01\x00")
                    assert stream.read(4) == b"\x05\x01\x00\x03"
                    length = stream.read(1)[0]
                    assert stream.read(length) == b"imap.invalid"
                    assert stream.read(2) == (993).to_bytes(2, "big")
                    addresses = {1: b"\x7f\x00\x00\x01", 3: b"\x05proxy", 4: b"\x00" * 15 + b"\x01"}
                    reply = b"\x05\x00\x00" + bytes([reply_type]) + addresses[reply_type] + b"\x03\xe1"
                    # 模拟 TCP 分片；欢迎消息紧随最后一个代理应答字节一起到达。
                    for value in reply[:-1]:
                        conn.sendall(bytes([value]))
                    conn.sendall(reply[-1:] + b"* OK IMAP ready\r\n")
                if scheme == "http":
                    conn.sendall(b"* OK IMAP ready\r\n")
                command = stream.readline()
                assert b"CAPABILITY" in command
                tag = command.split()[0]
                conn.sendall(b"* CAPABILITY IMAP4rev1 IDLE\r\n" + tag + b" OK done\r\n")
                stream.close()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        client = create_imap_client(
            "imap.invalid", 993, False, 3,
            f"{scheme}://{'user:p%40ss@' if authenticated else ''}127.0.0.1:{listener.getsockname()[1]}",
        )
        client.shutdown()
    finally:
        thread.join(6)
    assert not thread.is_alive()
    assert not errors


@pytest.mark.parametrize("value", ["https://secret:password@proxy:443", "socks5://proxy", "http://proxy:99999", "http://proxy:80/path"])
def test_invalid_proxy_does_not_leak_credentials(value):
    with pytest.raises(ValueError) as exc:
        parse_proxy_url(value)
    assert value not in str(exc.value)
    assert "password" not in str(exc.value)


def test_direct_connection_keeps_original_client():
    with patch("imapclient.IMAPClient") as factory:
        assert create_imap_client("imap.example", 993, True, 15) is factory.return_value
        factory.assert_called_once_with(host="imap.example", port=993, ssl=True, timeout=15)


def test_proxy_tls_verifies_original_mail_host():
    with patch("app.core.imap_proxy._create_proxy_socket") as factory, patch("imapclient.tls.wrap_socket", side_effect=RuntimeError("停止握手")) as wrap:
        with pytest.raises(RuntimeError, match="停止握手"):
            create_imap_client("imap.gmail.com", 993, True, 15, "socks5h://user:p%40ss@localhost:7890")
        wrap.assert_called_once_with(factory.return_value, None, "imap.gmail.com")
        factory.return_value.close.assert_called_once()


def test_connection_test_passes_proxy_and_mail_credentials():
    from app.core.email_watcher_service import EmailWatcherService

    with patch("app.core.email_watcher_service.create_imap_client") as factory:
        client = factory.return_value.__enter__.return_value
        client.search.return_value = [1, 2]
        result = EmailWatcherService()._do_test_connection(
            "imap.gmail.com", 993, True, "user", "app-password", "INBOX",
            "socks5h://localhost:7890",
        )
        assert result["success"]
        assert result["unseen_count"] == 2
        assert factory.call_args.kwargs["proxy_url"] == "socks5h://localhost:7890"
        client.login.assert_called_once_with("user", "app-password")


@pytest.mark.parametrize("scheme", ["http", "socks5", "socks5h"])
def test_failed_handshake_closes_socket(scheme):
    with patch("app.core.imap_proxy.socket.create_connection") as factory:
        factory.return_value.recv.return_value = b""
        with pytest.raises(OSError, match="代理不可达"):
            factory.return_value.sendall.side_effect = OSError("代理不可达")
            create_imap_client("imap.gmail.com", 993, True, 15, f"{scheme}://localhost:7890")
        factory.return_value.close.assert_called_once()


@pytest.mark.parametrize("scheme", ["socks5", "socks5h"])
def test_socks5_dns_selection(scheme):
    with patch("app.core.imap_proxy.socket.create_connection") as factory, patch("app.core.imap_proxy.socket.getaddrinfo") as resolve:
        resolve.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 993))]
        sock = factory.return_value
        sock.recv.side_effect = [b"\x05\x00", b"\x05\x00\x00\x01", b"\x7f\x00\x00\x01\x03\xe1"]
        result = _create_proxy_socket("imap.gmail.com", 993, 15, parse_proxy_url(f"{scheme}://localhost:7890"))
        assert result is sock
        request = sock.sendall.call_args.args[0]
        if scheme == "socks5":
            resolve.assert_called_once_with("imap.gmail.com", 993, type=socket.SOCK_STREAM)
            assert request == b"\x05\x01\x00\x01\xcb\x00\x71\x0a\x03\xe1"
        else:
            resolve.assert_not_called()
            assert request == b"\x05\x01\x00\x03\x0eimap.gmail.com\x03\xe1"
        sock.settimeout.assert_called_with(15)


@pytest.mark.parametrize("scheme,replies", [
    ("http", [bytes([value]) for value in b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"]),
    ("socks5h", [b"\x05\x02", b"\x01\x01"]),
    ("socks5h", [b"\x05\xff"]),
    ("socks5h", [b"\x05\x02", b"\x01\x00", b"\x05\x05\x00\x01", b"\x7f\x00\x00\x01\x03\xe1"]),
])
def test_proxy_refusal_does_not_expose_credentials(scheme, replies):
    with patch("app.core.imap_proxy.socket.create_connection") as factory:
        factory.return_value.recv.side_effect = replies
        with pytest.raises(OSError) as exc:
            _create_proxy_socket("imap.gmail.com", 993, 15, parse_proxy_url(f"{scheme}://user:secret@localhost:7890"))
        assert "secret" not in str(exc.value)
        factory.return_value.close.assert_called_once()


def test_handshake_timeout_closes_socket():
    with patch("app.core.imap_proxy.socket.create_connection") as factory:
        factory.return_value.recv.side_effect = TimeoutError("握手超时")
        with pytest.raises(TimeoutError):
            _create_proxy_socket("imap.gmail.com", 993, 15, parse_proxy_url("socks5h://localhost:7890"))
        factory.return_value.close.assert_called_once()
