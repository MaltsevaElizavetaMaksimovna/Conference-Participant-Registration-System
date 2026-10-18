import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
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

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("секретная деталь стека")

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


async def test_unhandled_exception_hides_details(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/boom")
    assert r.status_code == 500
    body = r.json()
    assert_error_shape(body)
    assert body["code"] == "internal_error"
    assert "секретная" not in r.text


def test_prod_requires_secret_key() -> None:
    with pytest.raises(ValueError, match="RS_SECRET_KEY"):
        Settings(env="prod")
    assert Settings(env="prod", secret_key="x" * 32).env == "prod"


def test_cors_origins_from_comma_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]
