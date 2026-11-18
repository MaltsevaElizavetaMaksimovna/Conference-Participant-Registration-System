from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import AppError


class Item(BaseModel):
    name: str = Field(min_length=1)
    qty: int


@pytest.fixture(autouse=True)
def _demo_routes(app: FastAPI) -> None:
    router = APIRouter(prefix="/_t")

    @router.post("/items")
    async def create_item(item: Item) -> Item:
        return item

    @router.get("/app-error")
    async def app_error() -> None:
        raise AppError("already_registered", "Уже зарегистрирован", 409, {"at": "12:00"})

    @router.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(403, "Нельзя")

    @router.post("/boom/{token}")
    async def boom(token: str, item: Item) -> None:
        raise RuntimeError(f"{token} {item.name}")

    @router.get("/stream-boom")
    async def stream_boom() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"first"
            raise RuntimeError("synthetic-stream-value")

        return StreamingResponse(chunks())

    app.include_router(router)


def assert_error_shape(body: dict[str, object]) -> None:
    assert set(body) == {"code", "message", "details"}
    assert isinstance(body["code"], str)
    assert isinstance(body["message"], str)
    assert isinstance(body["details"], dict)


async def test_404_format(client: httpx.AsyncClient) -> None:
    r = await client.get("/no/such/path")
    assert r.status_code == 404
    body = r.json()
    assert_error_shape(body)
    assert body["code"] == "not_found"


async def test_405_format(client: httpx.AsyncClient) -> None:
    r = await client.post("/health")
    assert r.status_code == 405
    assert r.json()["code"] == "method_not_allowed"


async def test_invalid_body_is_russian(client: httpx.AsyncClient) -> None:
    # Тело в cp1251 вместо UTF-8: так шлёт, например, консоль Windows
    body = '{"name": "Иван", "qty": 1}'.encode("cp1251")
    r = await client.post("/_t/items", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    data = r.json()
    assert_error_shape(data)
    assert data["code"] == "invalid_body"
    assert "UTF-8" in data["message"]


async def test_validation_error(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/items", json={"name": "", "qty": "abc"})
    assert r.status_code == 422
    body = r.json()
    assert_error_shape(body)
    assert body["code"] == "validation_error"
    assert set(body["details"]["fields"]) == {"name", "qty"}
    assert all(isinstance(v, str) for v in body["details"]["fields"].values())


async def test_app_error(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/app-error")
    assert r.status_code == 409
    assert r.json() == {
        "code": "already_registered",
        "message": "Уже зарегистрирован",
        "details": {"at": "12:00"},
    }


async def test_http_exception_custom_detail(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/http-error")
    assert r.status_code == 403
    body = r.json()
    assert_error_shape(body)
    assert (body["code"], body["message"]) == ("forbidden", "Нельзя")


async def test_unhandled_exception_hides_details(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="https://test",
    ) as client:
        origin = app.state.settings.cors_origins[0]
        r = await client.post(
            "/_t/boom/synthetic-path-token?photo_url=synthetic-url-secret",
            json={"name": "synthetic-exception-value", "qty": 1},
            headers={
                "Origin": origin,
                "Cookie": "rs_session=synthetic-cookie",
                "Authorization": "Agent synthetic-agent",
            },
        )
    assert r.status_code == 500
    assert r.headers["access-control-allow-origin"] == origin
    assert r.headers["access-control-allow-credentials"] == "true"
    body = r.json()
    assert_error_shape(body)
    assert body["code"] == "internal_error"
    assert "synthetic-exception-value" not in r.text
    assert "synthetic-" not in caplog.text
    assert "POST /_t/boom/{token}" in caplog.text
    assert "RuntimeError" in caplog.text


async def test_error_after_stream_started_hides_exception(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with pytest.raises(RuntimeError, match="Ошибка после начала HTTP-ответа") as raised:
            await client.get("/_t/stream-boom")
    assert raised.value.__suppress_context__
    assert "synthetic-stream-value" not in caplog.text
    assert "GET /_t/stream-boom" in caplog.text


def test_prod_requires_secret_key() -> None:
    with pytest.raises(ValueError, match="RS_SECRET_KEY"):
        Settings(env="prod")
    assert Settings(env="prod", secret_key="x" * 32).env == "prod"


def test_cors_origins_from_comma_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


async def test_cors_credentials_only_for_configured_origin(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    (allowed,) = app.state.settings.cors_origins
    for origin, expected_status in ((allowed, 200), ("https://unlisted.test", 400)):
        headers = {
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type, x-requested-with",
        }
        preflight = await client.options("/api/auth/me/printer", headers=headers)
        assert preflight.status_code == expected_status
        response = await client.get("/api/auth/me", headers={"Origin": origin})
        assert response.status_code == 401
        if origin == allowed:
            for result in (preflight, response):
                assert result.headers["access-control-allow-origin"] == origin
                assert result.headers["access-control-allow-credentials"] == "true"
                assert "Origin" in result.headers["vary"]
        else:
            assert "access-control-allow-origin" not in preflight.headers
            assert "access-control-allow-origin" not in response.headers
