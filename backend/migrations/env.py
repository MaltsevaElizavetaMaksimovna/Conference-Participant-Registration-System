"""Alembic: асинхронное окружение (SQLAlchemy async + psycopg 3).

URL берётся из `config.attributes["url"]` (программный запуск, тесты) или из Settings
(`RS_DATABASE_URL`). `alembic.ini` его не хранит.
"""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (регистрирует таблицы в Base.metadata)
from app.core.config import get_settings
from app.core.db import Base
from app.core.loop import selector_loop_factory

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url")
    return str(url) if url else get_settings().database_url


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def _run(coro: Coroutine[Any, Any, None]) -> None:
    """asyncio.run с Selector-циклом (psycopg async не работает на Proactor, Windows)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro, loop_factory=selector_loop_factory)
        return
    # Вызвано из работающего цикла (например, из async-теста): отдельный поток со своим циклом
    with ThreadPoolExecutor(max_workers=1) as pool_:
        pool_.submit(asyncio.run, coro, loop_factory=selector_loop_factory).result()


def run_migrations_online() -> None:
    _run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
