"""Public HTTP URL validation used by the documentation crawler."""

import asyncio
import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import httpx


@lru_cache(maxsize=512)
def _public_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) documentation URLs are allowed")
    if not _public_host(parsed.hostname.lower()):
        raise ValueError("Documentation URL must resolve to a public address")
    return url


async def safe_request(client: httpx.AsyncClient, method: str, url: str, *, timeout: float = 15):
    """Validate each redirect target before fetching it."""
    current = url
    for _ in range(6):
        await asyncio.to_thread(validate_public_url, current)
        response = await client.request(method, current, follow_redirects=False, timeout=timeout)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = urljoin(str(response.url), location)
        if response.status_code == 303:
            method = "GET"
    raise ValueError("Too many documentation redirects")
