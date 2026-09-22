"""Security helpers: URL validation, SSRF protection, token generation."""

from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
from urllib.parse import urlparse


class SecurityError(Exception):
    """Raised when a URL fails SSRF / scheme validation."""


def generate_token() -> str:
    return secrets.token_urlsafe(16)


def is_ip_allowed(ip: ipaddress._BaseAddress, allow_private: bool) -> bool:
    if allow_private:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url_sync(url: str, allow_private: bool = False) -> None:
    """Validate scheme, host and resolved IPs. Raises SecurityError.

    Uses blocking getaddrinfo; call from an executor if inside async code.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError(f"只允许 http/https 协议: {parsed.scheme or '(空)'}")
    host = parsed.hostname
    if not host:
        raise SecurityError("URL 缺少主机名")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not is_ip_allowed(ip, allow_private):
            raise SecurityError(f"禁止访问内网/保留地址: {host}")
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SecurityError(f"DNS 解析失败: {host}") from exc
    if not infos:
        raise SecurityError(f"DNS 解析失败: {host}")
    for info in infos:
        resolved = ipaddress.ip_address(info[4][0])
        if not is_ip_allowed(resolved, allow_private):
            raise SecurityError(f"主机 {host} 解析到禁止访问的地址: {resolved}")


async def validate_url(url: str, allow_private: bool = False) -> None:
    await asyncio.to_thread(validate_url_sync, url, allow_private)


def mask_url(url: str) -> str:
    """Hide the query string of a source URL for on-screen display."""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    return parsed._replace(query="****************").geturl()
