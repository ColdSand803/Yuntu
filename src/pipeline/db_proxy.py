"""Transparent HTTP CONNECT and SOCKS5 proxy tunneling for asyncpg."""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

_proxy_installed = False


def parse_proxy_url(proxy_url: str) -> dict[str, Any]:
    """Parse an HTTP or SOCKS5 proxy URL into connection parameters."""
    url = (proxy_url or "").strip()
    if not url:
        return {}
    if "://" not in url:
        url = f"http://{url}"
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https", "socks5", "socks5h"):
        raise ValueError(
            f"Unsupported DATABASE_PROXY scheme: {scheme!r}. "
            "Supported schemes: http, https, socks5, socks5h."
        )
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (1080 if "socks5" in scheme else (443 if scheme == "https" else 8080))
    username = urllib.parse.unquote(parsed.username) if parsed.username else None
    password = urllib.parse.unquote(parsed.password) if parsed.password else None
    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


async def _open_http_connect_tunnel(
    proxy_info: dict[str, Any],
    target_host: str,
    target_port: int,
    loop: asyncio.AbstractEventLoop,
    timeout: float = 20.0,
) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        try:
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 2000))
        except Exception:
            pass
    await asyncio.wait_for(
        loop.sock_connect(sock, (proxy_info["host"], proxy_info["port"])),
        timeout=timeout,
    )

    headers = [
        f"CONNECT {target_host}:{target_port} HTTP/1.1",
        f"Host: {target_host}:{target_port}",
        "Proxy-Connection: Keep-Alive",
    ]
    if proxy_info["username"] or proxy_info["password"]:
        user_pass = f"{proxy_info['username'] or ''}:{proxy_info['password'] or ''}"
        b64 = base64.b64encode(user_pass.encode("utf-8")).decode("ascii")
        headers.append(f"Proxy-Authorization: Basic {b64}")
    headers.append("\r\n")

    req_bytes = "\r\n".join(headers).encode("latin1")
    await asyncio.wait_for(loop.sock_sendall(sock, req_bytes), timeout=timeout)

    resp_buf = b""
    while b"\r\n\r\n" not in resp_buf:
        chunk = await asyncio.wait_for(loop.sock_recv(sock, 4096), timeout=timeout)
        if not chunk:
            sock.close()
            raise ConnectionError(
                f"HTTP proxy closed connection during CONNECT to {target_host}:{target_port}"
            )
        resp_buf += chunk
        if len(resp_buf) > 65536:
            sock.close()
            raise ConnectionError("HTTP proxy response header exceeded 64KB")

    header_part = resp_buf.split(b"\r\n\r\n", 1)[0]
    status_line = header_part.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or parts[1] != "200":
        sock.close()
        raise ConnectionError(
            f"HTTP proxy CONNECT to {target_host}:{target_port} failed: {status_line}"
        )

    return sock


async def _open_socks5_tunnel(
    proxy_info: dict[str, Any],
    target_host: str,
    target_port: int,
    loop: asyncio.AbstractEventLoop,
    timeout: float = 20.0,
) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        try:
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 2000))
        except Exception:
            pass
    await asyncio.wait_for(
        loop.sock_connect(sock, (proxy_info["host"], proxy_info["port"])),
        timeout=timeout,
    )

    user = proxy_info["username"]
    pwd = proxy_info["password"]
    if user or pwd:
        # methods: 00 (no auth), 02 (user/password)
        await asyncio.wait_for(loop.sock_sendall(sock, b"\x05\x02\x00\x02"), timeout=timeout)
    else:
        # method: 00 (no auth)
        await asyncio.wait_for(loop.sock_sendall(sock, b"\x05\x01\x00"), timeout=timeout)

    greet_resp = await asyncio.wait_for(loop.sock_recv(sock, 2), timeout=timeout)
    if len(greet_resp) < 2 or greet_resp[0] != 5:
        sock.close()
        raise ConnectionError("Invalid SOCKS5 greeting response from proxy")

    auth_method = greet_resp[1]
    if auth_method == 0x02:
        u_b = (user or "").encode("utf-8")
        p_b = (pwd or "").encode("utf-8")
        auth_msg = b"\x01" + bytes([len(u_b)]) + u_b + bytes([len(p_b)]) + p_b
        await asyncio.wait_for(loop.sock_sendall(sock, auth_msg), timeout=timeout)
        auth_resp = await asyncio.wait_for(loop.sock_recv(sock, 2), timeout=timeout)
        if len(auth_resp) < 2 or auth_resp[1] != 0:
            sock.close()
            raise ConnectionError("SOCKS5 proxy username/password authentication failed")
    elif auth_method != 0x00:
        sock.close()
        raise ConnectionError(f"SOCKS5 proxy rejected authentication method ({auth_method:#x})")

    # SOCKS5 CONNECT command
    try:
        ip_bytes = socket.inet_aton(target_host)
        addr_field = b"\x01" + ip_bytes
    except OSError:
        host_b = target_host.encode("utf-8")
        addr_field = b"\x03" + bytes([len(host_b)]) + host_b

    port_b = int(target_port).to_bytes(2, "big")
    req = b"\x05\x01\x00" + addr_field + port_b
    await asyncio.wait_for(loop.sock_sendall(sock, req), timeout=timeout)

    resp = await asyncio.wait_for(loop.sock_recv(sock, 4), timeout=timeout)
    if len(resp) < 4 or resp[1] != 0:
        err_code = resp[1] if len(resp) >= 2 else "unknown"
        sock.close()
        raise ConnectionError(f"SOCKS5 CONNECT to {target_host}:{target_port} failed (code={err_code})")

    atyp = resp[3]
    if atyp == 1:
        await asyncio.wait_for(loop.sock_recv(sock, 6), timeout=timeout)
    elif atyp == 3:
        len_b = await asyncio.wait_for(loop.sock_recv(sock, 1), timeout=timeout)
        await asyncio.wait_for(loop.sock_recv(sock, len_b[0] + 2), timeout=timeout)
    elif atyp == 4:
        await asyncio.wait_for(loop.sock_recv(sock, 18), timeout=timeout)

    return sock


async def open_proxied_socket(
    proxy_url: str,
    target_host: str,
    target_port: int,
    loop: asyncio.AbstractEventLoop | None = None,
    timeout: float = 20.0,
) -> socket.socket:
    """Establish a proxied TCP socket connection via HTTP CONNECT or SOCKS5."""
    if loop is None:
        loop = asyncio.get_running_loop()
    info = parse_proxy_url(proxy_url)
    scheme = info["scheme"]
    if scheme in ("http", "https"):
        return await _open_http_connect_tunnel(info, target_host, target_port, loop=loop, timeout=timeout)
    elif scheme in ("socks5", "socks5h"):
        return await _open_socks5_tunnel(info, target_host, target_port, loop=loop, timeout=timeout)
    else:
        raise ValueError(f"Unsupported proxy scheme: {scheme}")


def install_asyncpg_proxy_hook(proxy_url: str = "") -> None:
    """Hook asyncpg connection creator to tunnel through DATABASE_PROXY."""
    global _proxy_installed
    import asyncpg.connect_utils as cu
    from asyncpg import protocol

    if getattr(cu, "_yuntu_proxy_installed", False):
        return

    orig_connect_addr = cu.__connect_addr

    async def _proxied_connect_addr(
        params,
        retry,
        addr,
        loop,
        config,
        connection_class,
        record_class,
        params_input,
    ):
        from src.config import get_settings
        current_proxy = get_settings().database_proxy.strip()
        if current_proxy and isinstance(addr, tuple) and len(addr) == 2 and isinstance(addr[0], str):
            target_host, target_port = addr[0], int(addr[1])
            sock = await open_proxied_socket(current_proxy, target_host, target_port, loop=loop)
            connected = cu._create_future(loop)
            # Strip advisory SSL when tunneling over raw socket proxy to prevent server dropping on SSLRequest
            if params.ssl and params.ssl_negotiation is not cu.SSLNegotiation.direct:
                params = params._replace(ssl=None, sslmode=cu.SSLMode.disable)

            proto_factory = lambda: protocol.Protocol(addr, connected, params, record_class, loop)
            
            if params.ssl and params.ssl_negotiation is cu.SSLNegotiation.direct:
                connector = loop.create_connection(proto_factory, sock=sock, ssl=params.ssl)
            else:
                connector = loop.create_connection(proto_factory, sock=sock)

            tr, pr = await connector
            try:
                await connected
            except (
                cu.exceptions.InvalidAuthorizationSpecificationError,
                cu.exceptions.ConnectionDoesNotExistError,
            ):
                tr.close()
                if retry and (
                    params.sslmode == cu.SSLMode.allow and not pr.is_ssl or
                    params.sslmode == cu.SSLMode.prefer and pr.is_ssl
                ):
                    raise cu._RetryConnectSignal()
                raise
            except (Exception, asyncio.CancelledError):
                tr.close()
                raise

            con = connection_class(pr, tr, loop, addr, config, params_input)
            pr.set_connection(con)
            return con

        return await orig_connect_addr(
            params, retry, addr, loop, config, connection_class, record_class, params_input
        )

    cu.__connect_addr = _proxied_connect_addr
    cu._yuntu_proxy_installed = True
    _proxy_installed = True
    logger.info("Installed DATABASE_PROXY socket tunnel")


def check_and_install_db_proxy() -> None:
    """Read DATABASE_PROXY from settings and install hook if configured."""
    from src.config import get_settings
    proxy = get_settings().database_proxy.strip()
    if proxy:
        install_asyncpg_proxy_hook(proxy)