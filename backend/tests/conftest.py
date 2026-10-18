"""Фикстуры тестов.

RS_DATABASE_URL задан (CI) -> используем его. Иначе на сессию поднимается pgserver
во временной папке и создаётся БД regsys_test. На сессию БД приводится к `alembic upgrade head`.

`db` — AsyncSession в внешней транзакции, которая откатывается после теста
(`join_transaction_mode="create_savepoint"`: commit() внутри теста освобождает только savepoint).
"""

import asyncio
import os
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import migrate
from app.core.config import Settings
from app.core.db import get_session, make_engine
from app.core.security import hash_password
from app.main import create_app
from app.models.staff import Role, RolePermission, StaffUser

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


# ------------------------------------------------------------ сотрудники и вход


@pytest.fixture(scope="session", autouse=True)
def _fast_password_hashing() -> Iterator[None]:
    """Дешёвые параметры argon2 в тестах: иначе каждый вход тратит десятки миллисекунд."""
    from argon2 import PasswordHasher

    from app.core import security

    original = security._hasher
    security._hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    security.dummy_hash.cache_clear()
    yield
    security._hasher = original
    security.dummy_hash.cache_clear()


@pytest.fixture
async def app_db(app: FastAPI, db: AsyncSession) -> FastAPI:
    """Приложение, у которого сессия БД — тестовая `db` (всё откатывается после теста).

    Между запросами identity map очищается: так каждый запрос видит данные из БД,
    как отдельная сессия в бою.
    """

    async def _session() -> AsyncIterator[AsyncSession]:
        db.expunge_all()
        yield db

    app.dependency_overrides[get_session] = _session
    return app


@pytest.fixture
async def anon(app_db: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент без входа на приложении с тестовой БД (`app_db`)."""
    transport = httpx.ASGITransport(app=app_db, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class StaffClient(httpx.AsyncClient):
    """Клиент вошедшего сотрудника: cookie сессии и заголовок `X-Requested-With: rs`."""

    user_id: int
    role_id: int
    login: str
    password: str


async def create_role(db: AsyncSession, name: str | None = None, *permissions: str) -> Role:
    role = Role(name=name or f"role-{uuid.uuid4().hex[:8]}")
    db.add(role)
    await db.flush()
    db.add_all(RolePermission(role_id=role.id, permission=str(p)) for p in permissions)
    await db.commit()
    return role


async def create_user(
    db: AsyncSession,
    role: Role,
    login: str | None = None,
    password: str = "password-1",
    *,
    full_name: str = "Тестовый Сотрудник",
    blocked: bool = False,
) -> StaffUser:
    user = StaffUser(
        full_name=full_name,
        login=login or f"user-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(password),
        role_id=role.id,
        is_blocked=blocked,
    )
    db.add(user)
    await db.commit()
    return user


type LoginAs = Callable[..., Awaitable[StaffClient]]


@pytest.fixture
async def login_as(app_db: FastAPI, db: AsyncSession) -> AsyncIterator[LoginAs]:
    """`await login_as("users.manage", ...)`: роль с этими правами + сотрудник, вход через API.

    Именованные параметры: `login`, `password`, `role` (готовая Role вместо новой).
    Возвращает клиент с cookie сессии; каждый вызов — новый сотрудник и новая сессия.
    """
    clients: list[StaffClient] = []

    async def make(
        *permissions: str,
        login: str | None = None,
        password: str = "password-1",
        role: Role | None = None,
    ) -> StaffClient:
        role = role or await create_role(db, None, *permissions)
        user = await create_user(db, role, login, password)
        transport = httpx.ASGITransport(app=app_db, raise_app_exceptions=False)
        c = StaffClient(transport=transport, base_url="http://test")
        clients.append(c)
        r = await c.post("/api/auth/login", json={"login": user.login, "password": password})
        assert r.status_code == 200, r.text
        c.headers["X-Requested-With"] = "rs"
        c.user_id, c.role_id, c.login, c.password = user.id, role.id, user.login, password
        return c

    yield make
    for c in clients:
        await c.aclose()
