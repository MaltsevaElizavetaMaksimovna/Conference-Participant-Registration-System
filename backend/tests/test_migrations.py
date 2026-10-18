"""Миграции: подъём с нуля, откат до base и повторный подъём на отдельной БД."""

import psycopg
from alembic import command
from sqlalchemy.engine import make_url

import app.models  # noqa: F401
from app.cli import alembic_config, migrate
from app.core.db import Base


def _query(url: str, sql: str) -> list[tuple[object, ...]]:
    conninfo = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(conninfo) as conn:
        return conn.execute(sql).fetchall()  # type: ignore[arg-type]


def _tables(url: str) -> set[str]:
    rows = _query(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {str(r[0]) for r in rows}


def _has_function(url: str) -> bool:
    return bool(_query(url, "SELECT 1 FROM pg_proc WHERE proname = 'change_log_append_only'"))


def test_upgrade_downgrade_upgrade(temp_database_url: str) -> None:
    cfg = alembic_config(temp_database_url)
    expected = set(Base.metadata.tables) | {"alembic_version"}

    migrate(temp_database_url)
    assert _tables(temp_database_url) == expected
    assert _has_function(temp_database_url)

    command.downgrade(cfg, "base")
    assert _tables(temp_database_url) == {"alembic_version"}
    assert not _has_function(temp_database_url)

    migrate(temp_database_url)
    assert _tables(temp_database_url) == expected
    assert _has_function(temp_database_url)


def test_models_match_migrations(temp_database_url: str) -> None:
    """Аналог `alembic check`: после upgrade head автогенерация не находит различий."""
    migrate(temp_database_url)
    command.check(alembic_config(temp_database_url))
