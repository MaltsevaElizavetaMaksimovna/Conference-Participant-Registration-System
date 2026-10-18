import httpx

from app.core.config import Settings
from app.main import create_app


async def test_health_ok(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


async def test_health_db_unavailable() -> None:
    # порт 1 заведомо никто не слушает
    app = create_app(
        Settings(
            env="test",
            database_url="postgresql+psycopg://postgres@127.0.0.1:1/none",
            db_connect_timeout_s=2,
        )
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/health")
    finally:
        await app.state.engine.dispose()
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "db_unavailable"
    assert set(body) == {"code", "message", "details"}
