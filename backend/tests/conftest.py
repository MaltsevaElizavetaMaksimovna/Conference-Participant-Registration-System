"""Фикстуры тестов.

RS_DATABASE_URL задан (CI) -> используем его. Иначе на сессию поднимается pgserver
во временной папке и создаётся БД regsys_test.
"""

import asyncio
import os
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

TEST_DB = "regsys_test"

if sys.platform == "win32":
    # psycopg async не работает на ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("RS_DATABASE_URL"):
        yield url
        return

    import pgserver

    with tempfile.TemporaryDirectory(prefix="regsys_pg_", ignore_cleanup_errors=True) as tmp:
        server = pgserver.get_server(tmp, cleanup_mode="stop")
        try:
            uri = server.get_uri()
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            base = uri.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1)
            yield f"{base}/{TEST_DB}"
        finally:
            server.cleanup()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(env="test", database_url=database_url)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # raise_app_exceptions=False: проверяем, что клиент получает JSON-500, а не исключение
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
