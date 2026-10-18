"""CLI: bootstrap и seed-demo (на сессии `db`) и сквозной запуск main() на отдельной БД."""

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import (
    DEMO_CONFERENCE_TITLE,
    DEMO_PARTICIPANTS,
    bootstrap,
    demo_participant_rows,
    main,
    seed_demo,
)
from app.core.config import Settings, get_settings
from app.core.permissions import ADMIN_ROLE, DEFAULT_ROLES, REGISTRAR_ROLE, Permission
from app.core.text import full_name, normalize_search
from app.models import (
    Conference,
    ExtraFieldDef,
    Participant,
    Printer,
    Role,
    RolePermission,
    StaffUser,
    Terminal,
)


def make_settings(**kw: str) -> Settings:
    return Settings(env="test", **kw)  # type: ignore[arg-type]


async def count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def role_permissions(db: AsyncSession) -> dict[str, set[str]]:
    rows = await db.execute(
        select(Role.name, RolePermission.permission).join(
            RolePermission, RolePermission.role_id == Role.id
        )
    )
    result: dict[str, set[str]] = {}
    for name, perm in rows:
        result.setdefault(name, set()).add(perm)
    return result


async def test_bootstrap_twice_is_idempotent(db: AsyncSession) -> None:
    s = make_settings(bootstrap_admin_login="admin", bootstrap_admin_password="correct-horse")
    first = await bootstrap(db, s)
    second = await bootstrap(db, s)

    assert sorted(first.created_roles) == sorted(DEFAULT_ROLES)
    assert first.admin_login == "admin"
    assert second.created_roles == [] and second.added_permissions == {}
    assert second.admin_login is None

    assert await count(db, Role) == 2
    assert await count(db, StaffUser) == 1
    perms = await role_permissions(db)
    assert perms == {name: {str(p) for p in ps} for name, ps in DEFAULT_ROLES.items()}
    assert perms[ADMIN_ROLE] == {str(p) for p in Permission}
    assert Permission.IMPORTS_RUN not in perms[REGISTRAR_ROLE]
    assert await db.scalar(select(func.count()).select_from(Role).where(Role.is_system)) == 2

    admin = (await db.scalars(select(StaffUser))).one()
    role = await db.get(Role, admin.role_id)
    assert role is not None and role.name == ADMIN_ROLE
    assert admin.password_hash.startswith("$argon2")
    assert PasswordHasher().verify(admin.password_hash, "correct-horse")


async def test_bootstrap_without_credentials_creates_no_admin(db: AsyncSession) -> None:
    res = await bootstrap(db, make_settings())
    assert res.admin_login is None
    assert await count(db, Role) == 2
    assert await count(db, StaffUser) == 0
    # логин без пароля — тоже не создаём
    await bootstrap(db, make_settings(bootstrap_admin_login="admin"))
    assert await count(db, StaffUser) == 0


async def test_bootstrap_does_not_create_admin_when_staff_exists(db: AsyncSession) -> None:
    await bootstrap(db, make_settings())
    role = await db.scalar(select(Role).where(Role.name == REGISTRAR_ROLE))
    assert role is not None
    db.add(StaffUser(full_name="Анна", login="anna", password_hash="x", role_id=role.id))
    await db.flush()
    await bootstrap(db, make_settings(bootstrap_admin_login="admin", bootstrap_admin_password="p"))
    assert await count(db, StaffUser) == 1


async def test_bootstrap_restores_missing_permissions_and_keeps_extra(db: AsyncSession) -> None:
    await bootstrap(db, make_settings())
    registrar = await db.scalar(select(Role).where(Role.name == REGISTRAR_ROLE))
    assert registrar is not None
    # убрали обязательное право и добавили лишнее
    removed = await db.get(RolePermission, (registrar.id, Permission.STICKERS_PRINT.value))
    assert removed is not None
    await db.delete(removed)
    db.add(RolePermission(role_id=registrar.id, permission=Permission.IMPORTS_RUN))
    await db.flush()

    res = await bootstrap(db, make_settings())
    assert res.added_permissions == {REGISTRAR_ROLE: [Permission.STICKERS_PRINT.value]}
    perms = (await role_permissions(db))[REGISTRAR_ROLE]
    assert Permission.STICKERS_PRINT in perms
    assert Permission.IMPORTS_RUN in perms  # лишнее не удаляется


async def test_seed_demo_twice_no_duplicates(db: AsyncSession) -> None:
    first = await seed_demo(db)
    second = await seed_demo(db)
    assert first.participants_added == DEMO_PARTICIPANTS
    assert second.participants_added == 0
    assert (second.terminals_added, second.printers_added) == (0, 0)

    assert await count(db, Participant) == DEMO_PARTICIPANTS
    assert await count(db, Conference) == 1
    assert await count(db, Terminal) == 3 and await count(db, Printer) == 3
    assert await count(db, ExtraFieldDef) == 1

    conf = (await db.scalars(select(Conference))).one()
    assert conf.title == DEMO_CONFERENCE_TITLE
    assert conf.is_active and conf.badge_type == "single"
    assert {t.name for t in await db.scalars(select(Terminal))} == {
        "Терминал 1",
        "Терминал 2",
        "Терминал 3",
    }
    printers = list(await db.scalars(select(Printer)))
    assert {p.name for p in printers} == {"Принтер 1", "Принтер 2", "Принтер 3"}
    assert all((p.density, p.speed) == (10, 3) for p in printers)  # калибровка — по умолчанию


async def test_seed_demo_data_shape(db: AsyncSession) -> None:
    await seed_demo(db)
    people = list(await db.scalars(select(Participant).order_by(Participant.id)))
    ids = [p.external_id for p in people]
    assert ids[0] == "B24-1001" and ids[-1] == f"B24-{1000 + DEMO_PARTICIPANTS}"
    assert len(set(ids)) == DEMO_PARTICIPANTS

    for p in people:
        assert p.search_norm == normalize_search(
            full_name(p.last_name, p.first_name, p.middle_name)
        )
    assert any("ё" in (p.last_name + p.first_name).lower() for p in people)
    assert any(p.organization is None for p in people)
    assert any(p.organization is not None and len(p.organization) == 120 for p in people)
    assert any(p.last_name_en for p in people) and any(not p.last_name_en for p in people)
    assert any(p.extra.get("section") for p in people)
    assert all(p.source_data["last_name"] == p.last_name for p in people)
    assert not any("ё" in p.search_norm for p in people)


def test_seed_demo_rows_are_deterministic() -> None:
    assert demo_participant_rows(1) == demo_participant_rows(1)


async def test_seed_demo_keeps_foreign_active_conference(db: AsyncSession) -> None:
    db.add(
        Conference(
            title="Другая",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 2),
            badge_type="double",
            is_active=True,
        )
    )
    await db.flush()
    res = await seed_demo(db)
    assert res.conference_active is False
    assert await count(db, Participant) == DEMO_PARTICIPANTS


@pytest.fixture
def cli_env(temp_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("RS_ENV", "dev")
    monkeypatch.setenv("RS_DATABASE_URL", temp_database_url)
    monkeypatch.setenv("RS_BOOTSTRAP_ADMIN_LOGIN", "root")
    monkeypatch.setenv("RS_BOOTSTRAP_ADMIN_PASSWORD", "s3cret-pass")
    get_settings.cache_clear()
    yield temp_database_url
    get_settings.cache_clear()


def test_main_commands_end_to_end(cli_env: str) -> None:
    assert main(["migrate"]) == 0
    assert main(["bootstrap"]) == 0
    assert main(["seed-demo"]) == 0
    assert main(["bootstrap"]) == 0  # повторный запуск
    assert main(["seed-demo"]) == 0

    conninfo = make_url(cli_env).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(conninfo) as conn:

        def n(table: str) -> int:
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # type: ignore[arg-type]
            assert row is not None
            return int(row[0])

        assert n("participant") == DEMO_PARTICIPANTS
        assert n("role") == 2
        assert n("staff_user") == 1
        assert n("conference") == 1


def test_seed_demo_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_ENV", "prod")
    monkeypatch.setenv("RS_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("RS_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:1/none")
    get_settings.cache_clear()
    try:
        assert main(["seed-demo"]) == 1
    finally:
        get_settings.cache_clear()
