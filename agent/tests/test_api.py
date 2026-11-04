"""Тесты HTTP-клиента взаимодействия с сервером регистрации."""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from regsys_agent.api import AuthError, ServerClient


def test_worker_importable() -> None:
    """Проверка корректности экспорта и согласованности интерфейсов для Worker."""
    from regsys_agent.worker import Worker

    assert Worker is not None


def test_next_job_204_returns_none() -> None:
    """При отсутствии заданий сервер возвращает 204, клиент возвращает None."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        assert request.headers["Authorization"] == "Agent test_token_xyz"
        assert request.url.path == "/api/agent/jobs/next"
        assert request.url.params["wait"] == "20"
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000/", "test_token_xyz", transport=transport)
    try:
        job = client.next_job(wait_s=20)
        assert job is None
        assert called
    finally:
        client.close()


def test_next_job_200_returns_job() -> None:
    """При наличии задания сервер возвращает 200 с JSON, клиент декодирует PNG и параметры."""
    raw_png = b"\x89PNG\r\n\x1a\nfake_image_bytes"
    b64_png = base64.b64encode(raw_png).decode("ascii")

    payload: dict[str, Any] = {
        "job_id": 42,
        "copies": [
            {
                "png_base64": b64_png,
                "width_mm": 58.0,
                "height_mm": 80.0,
                "gap_mm": 2.0,
            }
        ],
        "offset_x_mm": -2.0,
        "offset_y_mm": 1.0,
        "density": 11,
        "speed": 4,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Agent valid_token"
        assert request.url.params["wait"] == "10"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000", "valid_token", transport=transport)
    try:
        job = client.next_job(wait_s=10)
        assert job is not None
        assert job.job_id == 42
        assert len(job.copies) == 1
        assert job.copies[0].png == raw_png
        assert job.copies[0].width_mm == 58.0
        assert job.copies[0].height_mm == 80.0
        assert job.copies[0].gap_mm == 2.0
        assert job.offset_x_mm == -2.0
        assert job.offset_y_mm == 1.0
        assert job.density == 11
        assert job.speed == 4
    finally:
        client.close()


def test_next_job_401_raises_auth_error() -> None:
    """Статус 401 вызывает AuthError, не раскрывающий токен в сообщении."""
    token = "secret_agent_token_value"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000", token, transport=transport)
    try:
        with pytest.raises(AuthError) as exc_info:
            client.next_job(wait_s=5)
        assert token not in str(exc_info.value)
    finally:
        client.close()


def test_next_job_errors_raise_httpx_error() -> None:
    """Сетевые сбои и 5xx при получении заданий пробрасываются наружу как httpx.HTTPError."""

    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler_500)
    client = ServerClient("http://regserver:8000", "tok", transport=transport)
    try:
        with pytest.raises(httpx.HTTPError):
            client.next_job(wait_s=5)
    finally:
        client.close()

    def handler_conn_err(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    transport_err = httpx.MockTransport(handler_conn_err)
    client_err = ServerClient("http://regserver:8000", "tok", transport=transport_err)
    try:
        with pytest.raises(httpx.HTTPError):
            client_err.next_job(wait_s=5)
    finally:
        client_err.close()


@pytest.mark.parametrize(
    ("status_code", "expected_return"),
    [
        (204, True),
        (404, True),
        (409, True),
        (500, False),
    ],
)
def test_send_result_status_codes(status_code: int, expected_return: bool) -> None:
    """Проверка обработки статусов ответа при отправке результата печати."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/agent/jobs/15/result"
        return httpx.Response(status_code)

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000", "tok", transport=transport)
    try:
        res = client.send_result(job_id=15, ok=True, error=None)
        assert res is expected_return
    finally:
        client.close()


def test_send_result_network_error_returns_false() -> None:
    """Сетевая ошибка при отправке результата возвращает False без падения."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network is down", request=request)

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000", "tok", transport=transport)
    try:
        res = client.send_result(job_id=15, ok=False, error="Printer error")
        assert res is False
    finally:
        client.close()


def test_send_result_401_raises_auth_error() -> None:
    """Статус 401 при отправке результата вызывает AuthError."""
    token = "secret_tok_123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    transport = httpx.MockTransport(handler)
    client = ServerClient("http://regserver:8000", token, transport=transport)
    try:
        with pytest.raises(AuthError) as exc_info:
            client.send_result(job_id=15, ok=True, error=None)
        assert token not in str(exc_info.value)
    finally:
        client.close()


def test_heartbeat_statuses() -> None:
    """Проверка отправки heartbeat: 204 возвращает True, ошибки возвращают False."""

    def handler_ok(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/agent/heartbeat"
        return httpx.Response(204)

    client_ok = ServerClient(
        "http://regserver:8000", "tok", transport=httpx.MockTransport(handler_ok)
    )
    try:
        assert client_ok.heartbeat("ready") is True
    finally:
        client_ok.close()

    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client_500 = ServerClient(
        "http://regserver:8000", "tok", transport=httpx.MockTransport(handler_500)
    )
    try:
        assert client_500.heartbeat("ready") is False
    finally:
        client_500.close()

    def handler_err(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed", request=request)

    client_err = ServerClient(
        "http://regserver:8000", "tok", transport=httpx.MockTransport(handler_err)
    )
    try:
        assert client_err.heartbeat("ready") is False
    finally:
        client_err.close()

    token = "top_secret_tok"

    def handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client_401 = ServerClient(
        "http://regserver:8000", token, transport=httpx.MockTransport(handler_401)
    )
    try:
        with pytest.raises(AuthError) as exc_info:
            client_401.heartbeat("ready")
        assert token not in str(exc_info.value)
    finally:
        client_401.close()
