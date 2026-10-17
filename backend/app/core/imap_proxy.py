"""邮件监听专用代理连接，不修改进程全局 socket。"""

import base64
import socket
import time
from urllib.parse import unquote, urlsplit


def parse_proxy_url(value: str):
    """校验代理地址；错误信息不包含账号密码。"""
    try:
        proxy = urlsplit(value.strip())
        if (
            proxy.scheme not in ("http", "socks5", "socks5h")
            or not proxy.hostname
            or not proxy.port
            or proxy.path not in ("", "/")
            or proxy.query
            or proxy.fragment
        ):
            raise ValueError
        return proxy
    except ValueError:
        raise ValueError("邮件代理地址无效，请填写 http://主机:端口 或 socks5h://主机:端口") from None


def _recv_exact(sock, size, deadline):
    """只读取握手所需字节，保留紧随代理应答到达的 IMAP 欢迎消息。"""
    data = bytearray()
    while len(data) < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("邮件代理握手超时")
            sock.settimeout(remaining)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("邮件代理在握手完成前断开连接")
        data.extend(chunk)
    return bytes(data)


def _connect_socks5(sock, proxy, host, port, deadline):
    """复用项目现有 socksio 协议状态机建立 TCP 隧道。"""
    import socksio

    conn = socksio.SOCKS5Connection()
    method = (
        socksio.SOCKS5AuthMethod.USERNAME_PASSWORD
        if proxy.username is not None
        else socksio.SOCKS5AuthMethod.NO_AUTH_REQUIRED
    )
    conn.send(socksio.SOCKS5AuthMethodsRequest([method]))
    sock.sendall(conn.data_to_send())
    response = conn.receive_data(_recv_exact(sock, 2, deadline))
    if response.method != method:
        raise OSError("邮件 SOCKS5 代理拒绝所选认证方式")
    if method == socksio.SOCKS5AuthMethod.USERNAME_PASSWORD:
        username = unquote(proxy.username).encode("utf-8")
        password = unquote(proxy.password or "").encode("utf-8")
        if not (1 <= len(username) <= 255 and 1 <= len(password) <= 255):
            raise ValueError("邮件 SOCKS5 代理账号和密码长度必须为 1–255 字节")
        conn.send(socksio.SOCKS5UsernamePasswordRequest(username, password))
        sock.sendall(conn.data_to_send())
        response = conn.receive_data(_recv_exact(sock, 2, deadline))
        if not response.success:
            raise OSError("邮件 SOCKS5 代理认证失败")

    target = host.encode("idna")
    if proxy.scheme == "socks5":
        target = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0].encode("ascii")
    conn.send(socksio.SOCKS5CommandRequest.from_address(socksio.SOCKS5Command.CONNECT, (target, port)))
    sock.sendall(conn.data_to_send())
    header = _recv_exact(sock, 4, deadline)
    if header[:1] != b"\x05" or header[2:3] != b"\x00":
        raise OSError("邮件 SOCKS5 代理返回无效应答")
    if header[3] == 1:
        suffix = _recv_exact(sock, 6, deadline)
    elif header[3] == 4:
        suffix = _recv_exact(sock, 18, deadline)
    elif header[3] == 3:
        length = _recv_exact(sock, 1, deadline)
        suffix = length + _recv_exact(sock, length[0] + 2, deadline)
    else:
        raise OSError("邮件 SOCKS5 代理返回未知地址类型")
    response = conn.receive_data(header + suffix)
    if response.reply_code != socksio.SOCKS5ReplyCode.SUCCEEDED:
        raise OSError(f"邮件 SOCKS5 代理连接被拒绝，状态码 {int.from_bytes(response.reply_code, 'big')}")


def _connect_http(sock, proxy, host, port, deadline):
    """用标准库建立 HTTP CONNECT 隧道，不消费隧道内的 IMAP 数据。"""
    target_host = host.encode("idna").decode("ascii")
    if any(char in target_host for char in "\r\n\t "):
        raise ValueError("IMAP 主机名无效")
    authority = f"[{target_host}]:{port}" if ":" in target_host else f"{target_host}:{port}"
    headers = [f"CONNECT {authority} HTTP/1.1", f"Host: {authority}"]
    if proxy.username is not None:
        credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
        token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {token}")
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
    response = bytearray()
    while not response.endswith(b"\r\n\r\n"):
        if len(response) >= 65536:
            raise OSError("邮件 HTTP 代理响应头过长")
        response.extend(_recv_exact(sock, 1, deadline))
    status = response.split(b"\r\n", 1)[0].split()
    if len(status) < 2 or status[0] not in (b"HTTP/1.0", b"HTTP/1.1") or not status[1].isdigit():
        raise OSError("邮件 HTTP 代理返回无效应答")
    if status[1] != b"200":
        raise OSError(f"邮件 HTTP 代理 CONNECT 失败，状态码 {int(status[1])}")


def _create_proxy_socket(host, port, timeout, proxy):
    deadline = time.monotonic() + timeout if timeout is not None else None
    sock = socket.create_connection((proxy.hostname, proxy.port), timeout=timeout)
    try:
        if proxy.scheme == "http":
            _connect_http(sock, proxy, host, port, deadline)
        else:
            _connect_socks5(sock, proxy, host, port, deadline)
        sock.settimeout(timeout)
        return sock
    except Exception:
        sock.close()
        raise


def create_imap_client(host, port, ssl, timeout, proxy_url=""):
    """HTTP 使用 CONNECT；socks5h 由代理解析邮箱域名，TLS 仍校验邮箱证书。"""
    from imapclient import IMAPClient

    if not proxy_url:
        return IMAPClient(host=host, port=port, ssl=ssl, timeout=timeout)

    from imapclient.imap4 import IMAP4WithTimeout
    from imapclient.tls import wrap_socket

    proxy = parse_proxy_url(proxy_url)

    class ProxyIMAP4(IMAP4WithTimeout):
        def _create_socket(self, timeout=None):
            sock = _create_proxy_socket(
                self.host, self.port,
                timeout if timeout is not None else self._timeout,
                proxy,
            )
            try:
                return wrap_socket(sock, None, self.host) if ssl else sock
            except Exception:
                sock.close()
                raise

    class ProxyIMAPClient(IMAPClient):
        def _create_IMAP4(self):
            return ProxyIMAP4(self.host, self.port, self._timeout.connect)

    return ProxyIMAPClient(host=host, port=port, ssl=ssl, timeout=timeout)
