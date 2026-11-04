"""Скачивание фото по ссылке: защита от SSRF, редиректы, лимиты (B1-06, IM-01)."""

import asyncio
import socket
from collections.abc import AsyncIterator

import httpx
import pytest

from app.imports.photo_fetch import PhotoFetchError, fetch_photo, is_public_address


# 1. Успешное скачивание по https и http: проверка хоста, заголовка Host и SNI
@pytest.mark.parametrize("scheme", ["https", "http"])
async def test_01_fetch_success(scheme: str) -> None:
    captured_requests: list[httpx.Request] = []
    expected_body = b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=expected_body)

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    url = f"{scheme}://photos.test/a.jpg"
    result = await fetch_photo(
        url,
        max_bytes=1000,
        timeout_s=5.0,
        max_redirects=3,
        resolve=fake_resolve,
        transport=httpx.MockTransport(handler),
    )

    assert result == expected_body
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.url.host == "93.184.216.34"
    assert req.headers["host"] == "photos.test"
    if scheme == "https":
        assert req.extensions.get("sni_hostname") == "photos.test"
    else:
        assert "sni_hostname" not in req.extensions


# 2. Нестандартный порт: URL запроса содержит порт, заголовок Host содержит порт
async def test_02_custom_port() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=b"custom-port-body")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    result = await fetch_photo(
        "https://photos.test:8443/a",
        max_bytes=1000,
        timeout_s=5.0,
        max_redirects=3,
        resolve=fake_resolve,
        transport=httpx.MockTransport(handler),
    )

    assert result == b"custom-port-body"
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert str(req.url) == "https://93.184.216.34:8443/a"
    assert req.headers["host"] == "photos.test:8443"


# 3. Некорректные ссылки: отказ bad_url, сетевой запрос не отправляется
@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://photos.test/a",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "photos.test/a",
        "http://user:pass@photos.test/a",
        "http://",
        "http://photos.test:99999/",
    ],
)
async def test_03_bad_url(bad_url: str) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=b"never-reached")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            bad_url,
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "bad_url"
    assert len(captured_requests) == 0


# 4. Непубличные адреса и литералы в ссылке: отказ blocked_address, handler не вызывался
@pytest.mark.parametrize(
    ("blocked_url", "resolved_ips"),
    [
        ("http://127.0.0.1/", None),
        ("http://localhost.test/", ["127.0.0.1"]),
        ("http://10.1.2.3/", None),
        ("http://192.168.0.10/", None),
        ("http://172.16.5.4/", None),
        ("http://169.254.169.254/", None),
        ("http://0.0.0.0/", None),
        ("http://[::1]/", None),
        ("http://[fe80::1]/", None),
        ("http://[fd00::1]/", None),
        ("http://[::ffff:127.0.0.1]/", None),
        ("http://100.64.0.1/", None),
        ("http://224.0.0.1/", None),
    ],
)
async def test_04_blocked_address_literal(blocked_url: str, resolved_ips: list[str] | None) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=b"never-reached")

    async def fake_resolve(host: str, port: int) -> list[str]:
        if resolved_ips is not None:
            return resolved_ips
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            blocked_url,
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "blocked_address"
    assert len(captured_requests) == 0


# 5. Смешанный DNS (публичный + приватный IP): отказ blocked_address, handler не вызывался
async def test_05_blocked_address_mixed_dns() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=b"never-reached")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/photo.jpg",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "blocked_address"
    assert len(captured_requests) == 0


# 6. Ошибка DNS (исключение OSError или пустой список адресов): отказ dns_failed
@pytest.mark.parametrize(
    "resolve_result",
    [
        socket.gaierror(-2, "Name or service not known"),
        [],
    ],
)
async def test_06_dns_failed(resolve_result: OSError | list[str]) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=b"never-reached")

    async def fake_resolve(host: str, port: int) -> list[str]:
        if isinstance(resolve_result, Exception):
            raise resolve_result
        return resolve_result

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/photo.jpg",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "dns_failed"
    assert len(captured_requests) == 0


# 7. Редирект на публичный адрес: оба запроса доходят до handler, тело скачано
async def test_07_redirect_public() -> None:
    captured_requests: list[httpx.Request] = []
    dns_map = {
        "photos.test": ["93.184.216.34"],
        "cdn.test": ["93.184.216.35"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.host == "93.184.216.34" and request.url.path == "/r":
            return httpx.Response(302, headers={"Location": "https://cdn.test/p.jpg"})
        if request.url.host == "93.184.216.35" and request.url.path == "/p.jpg":
            return httpx.Response(200, content=b"image-from-cdn")
        return httpx.Response(404)

    async def fake_resolve(host: str, port: int) -> list[str]:
        return dns_map[host]

    result = await fetch_photo(
        "https://photos.test/r",
        max_bytes=1000,
        timeout_s=5.0,
        max_redirects=3,
        resolve=fake_resolve,
        transport=httpx.MockTransport(handler),
    )

    assert result == b"image-from-cdn"
    assert len(captured_requests) == 2
    assert captured_requests[0].headers["host"] == "photos.test"
    assert captured_requests[1].headers["host"] == "cdn.test"


# 8. Редирект во внутреннюю сеть: отказ blocked_address, второй запрос не отправляется
@pytest.mark.parametrize(
    ("status_code", "redirect_location", "internal_ips"),
    [
        (302, "http://127.0.0.1/admin", None),
        (301, "http://internal.test/", ["10.0.0.1"]),
    ],
)
async def test_08_redirect_internal(
    status_code: int, redirect_location: str, internal_ips: list[str] | None
) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(status_code, headers={"Location": redirect_location})

    async def fake_resolve(host: str, port: int) -> list[str]:
        if host == "internal.test" and internal_ips:
            return internal_ips
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/r",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "blocked_address"
    assert len(captured_requests) == 1


# 9. Относительный редирект Location: /other.jpg ведет на тот же хост
async def test_09_redirect_relative() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path == "/orig.jpg":
            return httpx.Response(302, headers={"Location": "/other.jpg"})
        return httpx.Response(200, content=b"other-content")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    result = await fetch_photo(
        "https://photos.test/orig.jpg",
        max_bytes=1000,
        timeout_s=5.0,
        max_redirects=3,
        resolve=fake_resolve,
        transport=httpx.MockTransport(handler),
    )

    assert result == b"other-content"
    assert len(captured_requests) == 2
    assert captured_requests[0].url.path == "/orig.jpg"
    assert captured_requests[1].url.path == "/other.jpg"
    assert captured_requests[1].url.host == "93.184.216.34"
    assert captured_requests[1].headers["host"] == "photos.test"


# 10. Превышение количества редиректов: отказ too_many_redirects
async def test_10_too_many_redirects() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(302, headers={"Location": "/loop"})

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/loop",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=2,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "too_many_redirects"
    assert len(captured_requests) == 3


# 11. Некорректный статус ответа: 302 без Location, 404 и 500 вызывают отказ http_status
@pytest.mark.parametrize(
    ("status_code", "headers"),
    [
        (302, {}),
        (404, {}),
        (500, {}),
    ],
)
async def test_11_http_status(status_code: int, headers: dict[str, str]) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(status_code, headers=headers)

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/test.jpg",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=3,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "http_status"
    assert len(captured_requests) == 1


# 12. Превышение лимита: Content-Length, поток без заголовка, успех ровно в лимит
async def test_12_too_large() -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    # (а) заголовок Content-Length: 1000 при max_bytes=10
    def handler_declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "1000"}, content=b"x" * 10)

    with pytest.raises(PhotoFetchError) as exc_info_declared:
        await fetch_photo(
            "https://photos.test/a.jpg",
            max_bytes=10,
            timeout_s=5.0,
            max_redirects=1,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler_declared),
        )
    assert exc_info_declared.value.reason == "too_large"

    # (б) без Content-Length, тело 1000 байт потоком при max_bytes=10
    class ChunkedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(10):
                yield b"x" * 100

    def handler_stream(request: httpx.Request) -> httpx.Response:
        resp = httpx.Response(200, stream=ChunkedStream())
        resp.headers.pop("content-length", None)
        return resp

    with pytest.raises(PhotoFetchError) as exc_info_stream:
        await fetch_photo(
            "https://photos.test/a.jpg",
            max_bytes=10,
            timeout_s=5.0,
            max_redirects=1,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler_stream),
        )
    assert exc_info_stream.value.reason == "too_large"

    # (в) ровно max_bytes байт — успех
    def handler_exact(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10)

    result = await fetch_photo(
        "https://photos.test/a.jpg",
        max_bytes=10,
        timeout_s=5.0,
        max_redirects=1,
        resolve=fake_resolve,
        transport=httpx.MockTransport(handler_exact),
    )
    assert result == b"x" * 10


# 13. Таймаут запроса: долгий handler при малом timeout_s
async def test_13_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, content=b"ok")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/a.jpg",
            max_bytes=1000,
            timeout_s=0.1,
            max_redirects=1,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "timeout"


# 14. Сетевая ошибка транспортного уровня: ConnectError вызывает отказ network
async def test_14_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            "https://photos.test/a.jpg",
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=1,
            resolve=fake_resolve,
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.reason == "network"


# 15. Проверка публичности адресов функцией is_public_address
@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("8.8.8.8", True),
        ("2001:4860:4860::8888", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("::ffff:10.0.0.1", False),
        ("100.64.0.1", False),
        ("224.0.0.1", False),
    ],
)
def test_15_is_public_address(address: str, expected: bool) -> None:
    assert is_public_address(address) is expected


# 16. Ссылка не попадает в сообщение об ошибке и поле reason
async def test_16_error_message_no_url() -> None:
    url = "https://photos.test/secret-folder/photo.jpg"

    def dummy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def resolve_fail(host: str, port: int) -> list[str]:
        return []

    with pytest.raises(PhotoFetchError) as exc_info:
        await fetch_photo(
            url,
            max_bytes=1000,
            timeout_s=5.0,
            max_redirects=1,
            resolve=resolve_fail,
            transport=httpx.MockTransport(dummy_handler),
        )

    err = exc_info.value
    assert "photos.test" not in str(err)
    assert "photos.test" not in err.reason
    assert "secret-folder" not in str(err)
    assert "secret-folder" not in err.reason
