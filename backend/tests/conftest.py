"""Фикстуры тестов.

RS_DATABASE_URL задан (CI) -> используем его. Иначе на сессию поднимается pgserver
во временной папке и создаётся БД regsys_test. На сессию БД приводится к `alembic upgrade head`.

`db` — AsyncSession в внешней транзакции, которая откатывается после теста
(`join_transaction_mode="create_savepoint"`: commit() внутри теста освобождает только savepoint).
"""

import asyncio
import itertools
import os
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import migrate
from app.core.config import Settings
from app.core.db import get_session, make_engine
from app.main import create_app
from app.models.device import Printer, Terminal
from app.terminals.tokens import AGENT_PREFIX, TERMINAL_PREFIX, generate_token, hash_token

TEST_DB = "regsys_test"

if sys.platform == "win32":
    # psycopg async не работает на ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _conninfo(sa_url: str, database: str | None = None) -> str:
    """URL SQLAlchemy -> строка подключения psycopg (при необходимости с другой БД)."""
    url = make_url(sa_url)
    if database:
        url = url.set(database=database)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def _server_url() -> Iterator[str]:
    """URL БД тестового сервера (без миграций)."""
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


@pytest.fixture(scope="session")
def database_url(_server_url: str) -> str:
    migrate(_server_url)
    return _server_url


@pytest.fixture
def temp_database_url(_server_url: str) -> Iterator[str]:
    """Отдельная пустая БД на том же сервере (для тестов миграций и CLI)."""
    name = f"regsys_tmp_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_conninfo(_server_url, "postgres"), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            yield make_url(_server_url).set(database=name).render_as_string(hide_password=False)
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


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


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[AsyncSession]:
    """Сессия, изолированная от остальных тестов: всё откатывается в конце."""
    engine = make_engine(database_url)
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            session = AsyncSession(
                bind=conn,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                yield session
            finally:
                await session.close()
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def db_client(
    app: FastAPI, db: AsyncSession, client: httpx.AsyncClient
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент, чьи запросы работают в сессии `db` (после теста всё откатывается)."""

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    yield client
    app.dependency_overrides.pop(get_session, None)


class Devices:
    """Фабрика терминалов и принтеров с токенами для тестов."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._n = itertools.count(1)

    async def printer(
        self,
        name: str | None = None,
        *,
        token: bool = True,
        status: str = "unknown",
        seen_ago_s: float | None = None,
        **fields: object,
    ) -> tuple[Printer, str]:
        """(принтер, токен агента); токен пустой, если `token=False`."""
        raw = generate_token(AGENT_PREFIX) if token else ""
        printer = Printer(
            name=name or f"Принтер {next(self._n)}",
            agent_token_hash=hash_token(raw) if token else None,
            status=status,
            last_seen_at=None if seen_ago_s is None else _ago(seen_ago_s),
            **fields,
        )
        self._db.add(printer)
        await self._db.commit()
        return printer, raw

    async def terminal(
        self,
        name: str | None = None,
        *,
        token: bool = True,
        enabled: bool = True,
        printer: Printer | None = None,
        seen_ago_s: float | None = None,
    ) -> tuple[Terminal, str]:
        """(терминал, токен); токен пустой, если `token=False`."""
        raw = generate_token(TERMINAL_PREFIX) if token else ""
        terminal = Terminal(
            name=name or f"Терминал {next(self._n)}",
            token_hash=hash_token(raw) if token else None,
            is_enabled=enabled,
            printer_id=printer.id if printer else None,
            last_seen_at=None if seen_ago_s is None else _ago(seen_ago_s),
        )
        self._db.add(terminal)
        await self._db.commit()
        return terminal, raw


def _ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


@pytest.fixture
def devices(db: AsyncSession) -> Devices:
    return Devices(db)
