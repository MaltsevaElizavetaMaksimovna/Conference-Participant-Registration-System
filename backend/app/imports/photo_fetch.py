"""Скачивание фото по ссылке из файла импорта с защитой от SSRF (B1-06, IM-01).

Ссылку присылает тот, кто готовит файл, поэтому сервер не должен ходить по ней во внутреннюю сеть:
- только `http`/`https`, без логина и пароля в ссылке;
- имя хоста резолвится заранее, и ВСЕ адреса должны быть публичными (не loopback, не частные сети,
  не link-local и метаданные облака, не multicast и т.п.);
- соединение идёт на уже проверенный IP (повторного резолва, а значит и DNS rebinding, нет); для
  https имя хоста передаётся в SNI и проверку сертификата;
- редиректы не выполняются автоматически: каждый новый адрес проходит те же проверки, их не больше
  `max_redirects`;
- тело читается потоком и обрывается на `max_bytes`; общий таймаут на всё скачивание;
- прокси из окружения и cookies не используются.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# (хост, порт) -> IP-адреса строками
Resolver = Callable[[str, int], Awaitable[list[str]]]


class PhotoFetchError(Exception):
    """Фото по ссылке не скачано. `reason` — машинная причина (в отчёт и лог без самой ссылки)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def resolve_host(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _parse(url: str) -> tuple[str, str, int]:
    """(схема, хост, порт) допустимой ссылки, иначе `bad_url`."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise PhotoFetchError("bad_url") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise PhotoFetchError("bad_url")
    return scheme, parts.hostname, port or (443 if scheme == "https" else 80)


async def _pinned_address(host: str, port: int, resolve: Resolver) -> str:
    """Публичный IP хоста; если среди адресов есть непубличный — отказ целиком."""
    try:
        is_literal = bool(ipaddress.ip_address(host))
    except ValueError:
        is_literal = False
    if is_literal:
        addresses = [host]
    else:
        try:
            addresses = await resolve(host, port)
        except OSError:
            raise PhotoFetchError("dns_failed") from None
    if not addresses:
        raise PhotoFetchError("dns_failed")
    if not all(is_public_address(a) for a in addresses):
        raise PhotoFetchError("blocked_address")
    return addresses[0]


def _pinned_url(url: str, address: str) -> str:
    parts = urlsplit(url)
    ip_host = f"[{address}]" if ":" in address else address
    netloc = f"{ip_host}:{parts.port}" if parts.port else ip_host
    return parts._replace(netloc=netloc).geturl()


async def _download(
    client: httpx.AsyncClient, url: str, *, max_bytes: int, max_redirects: int, resolve: Resolver
) -> bytes:
    for _ in range(max_redirects + 1):
        scheme, host, port = _parse(url)
        address = await _pinned_address(host, port, resolve)
        bare = f"[{host}]" if ":" in host else host
        host_header = bare if port in (80, 443) else f"{bare}:{port}"
        request = client.build_request(
            "GET",
            _pinned_url(url, address),
            headers={"Host": host_header, "Accept": "image/*", "Accept-Encoding": "identity"},
            extensions={"sni_hostname": host} if scheme == "https" else {},
        )
        response = await client.send(request, stream=True)
        try:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise PhotoFetchError("http_status")
                url = urljoin(url, location)
                continue
            if response.status_code != 200:
                raise PhotoFetchError("http_status")
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                raise PhotoFetchError("too_large")
            body = bytearray()
            # распакованные куски: сжатое тело (если сервер всё же сжал) тоже упирается в лимит
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise PhotoFetchError("too_large")
            return bytes(body)
        finally:
            await response.aclose()
    raise PhotoFetchError("too_many_redirects")


async def fetch_photo(
    url: str,
    *,
    max_bytes: int,
    timeout_s: float,
    max_redirects: int,
    resolve: Resolver = resolve_host,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Байты по ссылке или `PhotoFetchError`. `resolve`/`transport` подменяются в тестах."""
    try:
        async with (
            asyncio.timeout(timeout_s),
            httpx.AsyncClient(
                transport=transport,
                timeout=timeout_s,
                follow_redirects=False,
                trust_env=False,
            ) as client,
        ):
            return await _download(
                client, url, max_bytes=max_bytes, max_redirects=max_redirects, resolve=resolve
            )
    except (TimeoutError, httpx.TimeoutException):
        raise PhotoFetchError("timeout") from None
    except httpx.HTTPError:
        raise PhotoFetchError("network") from None
