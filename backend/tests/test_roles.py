"""Роли и разрешения (B1-02, AD-04): проверки заказчика, «права со следующего входа»,
защита от потери последнего администратора, гонки."""

import asyncio
import contextlib
import typing
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import migrate
from app.core.config import Settings
from app.core.db import make_engine, make_sessionmaker
from app.core.permissions import DEFAULT_ROLES, PERMISSION_TITLES, Permission
from app.main import create_app
from app.models.staff import Role, RolePermission, StaffUser
from app.roles import service as roles_service
from app.roles.schemas import PermissionCode
from tests.conftest import LoginAs, create_role, create_user

REGISTRAR = sorted(str(p) for p in DEFAULT_ROLES["Регистратор"])
ALL = [str(p) for p in Permission]


def _perms(role: dict[str, typing.Any]) -> list[str]:
    result: list[str] = role["permissions"]
    return result


async def _db_permissions(db: AsyncSession, role_id: int) -> set[str]:
    return set(
        await db.scalars(select(RolePermission.permission).where(RolePermission.role_id == role_id))
    )


# ---------------------------------------------------------------- каталог


def test_permission_code_literal_matches_enum() -> None:
    assert set(typing.get_args(PermissionCode)) == {str(p) for p in Permission}


async def test_permissions_catalog(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.get("/api/admin/permissions")
    assert r.status_code == 200
    assert r.json() == [{"code": str(p), "title": t} for p, t in PERMISSION_TITLES.items()]


# ---------------------------------------------------------------- CRUD ролей


async def test_create_and_list_roles(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.post(
        "/api/admin/roles",
        json={
            "name": "  Старший регистратор ",
            "permissions": ["stickers.print", "participants.view", "stickers.print"],
        },
    )
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["name"] == "Старший регистратор"
    assert role["is_system"] is False
    assert role["users_count"] == 0
    assert _perms(role) == ["participants.view", "stickers.print"]  # без дублей, в порядке каталога

    r = await admin.get("/api/admin/roles")
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 2  # роль админа + новая
    by_id = {x["id"]: x for x in page["items"]}
    assert by_id[role["id"]] == role
    assert by_id[admin.role_id]["users_count"] == 1

    r = await admin.get("/api/admin/roles", params={"limit": 1, "offset": 1})
    assert len(r.json()["items"]) == 1
    assert r.json()["total"] == 2


async def test_create_role_validation(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.post("/api/admin/roles", json={"name": "   ", "permissions": []})
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["name"] == "Укажите название роли"
    r = await admin.post("/api/admin/roles", json={"name": "X", "permissions": ["no.such"]})
    assert r.status_code == 422
    r = await admin.post("/api/admin/roles", json={"name": "Пустая", "permissions": []})
    assert r.status_code == 201
    assert r.json()["permissions"] == []


async def test_role_name_must_be_unique_ignoring_case(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    body = {"name": "Волонтёр", "permissions": ["participants.view"]}
    assert (await admin.post("/api/admin/roles", json=body)).status_code == 201
    r = await admin.post("/api/admin/roles", json={**body, "name": "волонтёр"})
    assert r.status_code == 409
    assert r.json()["code"] == "role_name_taken"

    other = (await admin.post("/api/admin/roles", json={**body, "name": "Другая"})).json()
    r = await admin.put(f"/api/admin/roles/{other['id']}", json={**body, "name": "ВОЛОНТЁР"})
    assert r.status_code == 409
    assert r.json()["code"] == "role_name_taken"
    # Сохранить роль под её же названием можно
    r = await admin.put(f"/api/admin/roles/{other['id']}", json={**body, "name": "Другая"})
    assert r.status_code == 200


async def test_update_role(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    role = (
        await admin.post(
            "/api/admin/roles", json={"name": "Черновик", "permissions": ["participants.view"]}
        )
    ).json()
    r = await admin.put(
        f"/api/admin/roles/{role['id']}",
        json={"name": "Чистовик", "permissions": ["stickers.print", "participants.add"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Чистовик"
    assert set(_perms(r.json())) == {"stickers.print", "participants.add"}
    assert await _db_permissions(db, role["id"]) == {"stickers.print", "participants.add"}


async def test_unknown_role_is_404(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    body = {"name": "X", "permissions": []}
    r = await admin.put("/api/admin/roles/987654", json=body)
    assert r.status_code == 404
    assert r.json()["code"] == "role_not_found"
    r = await admin.delete("/api/admin/roles/987654")
    assert r.status_code == 404
    assert r.json()["code"] == "role_not_found"


# ----------------------------------------------- проверки заказчика (AD-04)


async def test_senior_registrar_gets_import_but_not_template_settings(
    login_as: LoginAs, anon: httpx.AsyncClient
) -> None:
    """«Старший регистратор» = права регистратора + загрузка участников."""
    admin = await login_as("users.manage")
    registrar = (
        await admin.post("/api/admin/roles", json={"name": "Регистратор", "permissions": REGISTRAR})
    ).json()
    senior = (
        await admin.post(
            "/api/admin/roles",
            json={
                "name": "Старший регистратор",
                "permissions": [*registrar["permissions"], "imports.run"],
            },
        )
    ).json()
    user = (
        await admin.post(
            "/api/admin/users",
            json={
                "full_name": "Старшая Регистраторша",
                "login": "senior",
                "password": "senior-pass-1",
                "role_id": senior["id"],
            },
        )
    ).json()
    assert user["role"] == {"id": senior["id"], "name": "Старший регистратор"}

    c = anon
    r = await c.post("/api/auth/login", json={"login": "senior", "password": "senior-pass-1"})
    assert r.status_code == 200, r.text
    assert (await c.get("/api/admin/import-template.xlsx")).status_code == 200  # загрузка доступна
    r = await c.get("/api/admin/conferences")  # настройка конференций и шаблонов недоступна
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    r = await c.get("/api/admin/conferences/1/templates")
    assert r.status_code == 403
    assert (await c.get("/api/participants/stats")).status_code == 200  # права регистратора есть


async def test_removing_permission_from_registrar_takes_effect_on_next_login(
    login_as: LoginAs, db: AsyncSession
) -> None:
    """Убрали у «Регистратора» «Добавление участника»: права нет (со следующего входа)."""
    admin = await login_as("users.manage")
    role = await create_role(db, "Регистратор", *REGISTRAR)
    reg = await login_as(role=role)
    dup = {"last_name": "Иванов", "first_name": "Пётр"}
    assert (await reg.post("/api/participants/check-duplicates", json=dup)).status_code == 200

    new_perms = [p for p in REGISTRAR if p != "participants.add"]
    r = await admin.put(
        f"/api/admin/roles/{role.id}", json={"name": "Регистратор", "permissions": new_perms}
    )
    assert r.status_code == 200
    assert "participants.add" not in _perms(r.json())

    # Уже вошедший сотрудник сохраняет права до следующего входа (снимок в сессии)
    assert (await reg.post("/api/participants/check-duplicates", json=dup)).status_code == 200
    assert "participants.add" in (await reg.get("/api/auth/me")).json()["permissions"]

    # После повторного входа права уже без «Добавления участника»
    r = await reg.post("/api/auth/login", json={"login": reg.login, "password": reg.password})
    assert r.status_code == 200
    assert "participants.add" not in r.json()["permissions"]
    r = await reg.post("/api/participants/check-duplicates", json=dup)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert (await reg.get("/api/participants/stats")).status_code == 200  # остальное на месте


async def test_adding_permission_also_waits_for_next_login(
    login_as: LoginAs, db: AsyncSession
) -> None:
    admin = await login_as("users.manage")
    role = await create_role(db, None, "participants.view")
    c = await login_as(role=role)
    await admin.put(
        f"/api/admin/roles/{role.id}",
        json={"name": role.name, "permissions": ["participants.view", "imports.run"]},
    )
    assert (await c.get("/api/admin/import-template.xlsx")).status_code == 403
    await c.post("/api/auth/login", json={"login": c.login, "password": c.password})
    assert (await c.get("/api/admin/import-template.xlsx")).status_code == 200


async def test_assigned_role_cannot_be_deleted(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    role = await create_role(db, "Регистратор", *REGISTRAR)
    await login_as(role=role)
    await login_as(role=role)

    r = await admin.delete(f"/api/admin/roles/{role.id}")
    assert r.status_code == 409
    assert r.json()["code"] == "role_in_use"
    assert r.json()["message"] == "Роль назначена сотрудникам — сначала смените им роль"
    assert r.json()["details"] == {"users_count": 2}
    assert await _db_permissions(db, role.id) == set(REGISTRAR)  # роль на месте


async def test_unassigned_role_can_be_deleted(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    role = (
        await admin.post(
            "/api/admin/roles", json={"name": "Лишняя", "permissions": ["participants.view"]}
        )
    ).json()
    r = await admin.delete(f"/api/admin/roles/{role['id']}")
    assert r.status_code == 204
    assert r.content == b""
    assert await db.scalar(select(Role.id).where(Role.id == role["id"])) is None
    assert await _db_permissions(db, role["id"]) == set()  # права удалены каскадом
    ids = [x["id"] for x in (await admin.get("/api/admin/roles")).json()["items"]]
    assert role["id"] not in ids


async def test_role_becomes_deletable_after_users_move_away(
    login_as: LoginAs, db: AsyncSession
) -> None:
    admin = await login_as("users.manage")
    old = await create_role(db, "Старая", "participants.view")
    new = await create_role(db, "Новая", "participants.view")
    user = await login_as(role=old)
    assert (await admin.delete(f"/api/admin/roles/{old.id}")).status_code == 409
    r = await admin.put(f"/api/admin/users/{user.user_id}", json={"role_id": new.id})
    assert r.status_code == 200
    assert (await admin.delete(f"/api/admin/roles/{old.id}")).status_code == 204


async def test_sole_admin_cannot_lose_users_manage(login_as: LoginAs, db: AsyncSession) -> None:
    """Убрать «Управление учётными записями и ролями» у единственного администратора нельзя."""
    admin = await login_as("users.manage", "participants.view")
    r = await admin.put(
        f"/api/admin/roles/{admin.role_id}",
        json={"name": "Админ", "permissions": ["participants.view"]},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "last_admin_permission"
    assert "Нельзя оставить систему без администратора" in r.json()["message"]
    # Ничего не изменилось
    assert await _db_permissions(db, admin.role_id) == {"users.manage", "participants.view"}
    assert (await admin.get("/api/admin/roles")).status_code == 200
    # Остальные права той же роли править можно
    r = await admin.put(
        f"/api/admin/roles/{admin.role_id}",
        json={"name": "Админ", "permissions": ["users.manage"]},
    )
    assert r.status_code == 200


async def test_admin_role_can_be_stripped_if_another_active_admin_exists(
    login_as: LoginAs, db: AsyncSession
) -> None:
    admin_a = await login_as("users.manage")
    await login_as("users.manage")  # второй администратор в другой роли
    r = await admin_a.put(
        f"/api/admin/roles/{admin_a.role_id}", json={"name": "Бывший админ", "permissions": []}
    )
    assert r.status_code == 200


async def test_blocked_admin_does_not_count(login_as: LoginAs, db: AsyncSession) -> None:
    admin_a = await login_as("users.manage")
    role_b = await create_role(db, None, "users.manage")
    await create_user(db, role_b, "blocked-admin", blocked=True)
    r = await admin_a.put(
        f"/api/admin/roles/{admin_a.role_id}", json={"name": "Бывший админ", "permissions": []}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "last_admin_permission"
    # Разблокировали второго — теперь можно
    blocked_id = await db.scalar(select(StaffUser.id).where(StaffUser.login == "blocked-admin"))
    await db.execute(update(StaffUser).where(StaffUser.id == blocked_id).values(is_blocked=False))
    await db.commit()
    r = await admin_a.put(
        f"/api/admin/roles/{admin_a.role_id}", json={"name": "Бывший админ", "permissions": []}
    )
    assert r.status_code == 200


async def test_role_without_users_manage_can_be_edited_freely(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    role = (
        await admin.post(
            "/api/admin/roles", json={"name": "Просмотр", "permissions": ["participants.view"]}
        )
    ).json()
    r = await admin.put(
        f"/api/admin/roles/{role['id']}", json={"name": "Просмотр", "permissions": []}
    )
    assert r.status_code == 200


async def test_stale_admin_session_keeps_working_until_relogin(login_as: LoginAs) -> None:
    """Администратор, у чьей роли отозвали users.manage, работает до выхода (AD-04)."""
    admin_a = await login_as("users.manage")
    admin_b = await login_as("users.manage")
    r = await admin_a.put(
        f"/api/admin/roles/{admin_a.role_id}", json={"name": "Бывший админ", "permissions": []}
    )
    assert r.status_code == 200
    assert (await admin_a.get("/api/admin/roles")).status_code == 200
    await admin_a.post(
        "/api/auth/login", json={"login": admin_a.login, "password": admin_a.password}
    )
    assert (await admin_a.get("/api/admin/roles")).status_code == 403
    # Оставшийся администратор теперь защищён инвариантом
    r = await admin_b.put(
        f"/api/admin/roles/{admin_b.role_id}", json={"name": "X", "permissions": []}
    )
    assert r.status_code == 409


# ------------------------------------------------------------- гонки


@pytest.fixture
def race_barrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заставляет два запроса дойти до проверки инварианта, пока ни один не закоммитил.

    Без блокировки оба видят «второй администратор на месте» и оба проходят (write skew).
    С блокировкой второй запрос ждёт первого на `lock_staff_admin` и до барьера не доходит,
    поэтому первый после короткого ожидания идёт дальше один.
    """
    arrived = 0
    both_here = asyncio.Event()
    original = roles_service.ensure_admin_remains

    async def with_barrier(session: AsyncSession) -> None:
        nonlocal arrived
        arrived += 1
        if arrived >= 2:
            both_here.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_here.wait(), timeout=0.7)
        await original(session)

    monkeypatch.setattr(roles_service, "ensure_admin_remains", with_barrier)


@pytest.fixture
async def real_app(temp_database_url: str) -> AsyncIterator[FastAPI]:
    """Приложение на отдельной, настоящей БД: сессии реально параллельны и коммитятся."""
    await asyncio.to_thread(migrate, temp_database_url)
    app = create_app(Settings(env="test", database_url=temp_database_url))
    yield app
    await app.state.engine.dispose()


async def _admin_in_own_role(app: FastAPI, n: int) -> tuple[int, str]:
    engine = make_engine(app.state.settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            role = await create_role(s, f"Админ {n}", "users.manage")
            user = await create_user(s, role, f"admin{n}", "password-1")
            return role.id, user.login
    finally:
        await engine.dispose()


async def test_two_admins_cannot_strip_each_other_concurrently(
    real_app: FastAPI,
    race_barrier: None,
) -> None:
    """Классический write skew: два администратора одновременно лишают права свои роли."""
    app = real_app
    clients: list[httpx.AsyncClient] = []
    role_ids: list[int] = []
    for n in (1, 2):
        role_id, login = await _admin_in_own_role(app, n)
        role_ids.append(role_id)
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"X-Requested-With": "rs"},
        )
        r = await c.post("/api/auth/login", json={"login": login, "password": "password-1"})
        assert r.status_code == 200
        clients.append(c)

    async def strip(c: httpx.AsyncClient, role_id: int) -> httpx.Response:
        return await c.put(
            f"/api/admin/roles/{role_id}", json={"name": f"Бывший {role_id}", "permissions": []}
        )

    responses = await asyncio.gather(
        *(strip(c, rid) for c, rid in zip(clients, role_ids, strict=True))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409], [r.text for r in responses]
    failed = next(r for r in responses if r.status_code == 409)
    assert failed.json()["code"] == "last_admin_permission"

    # В БД ровно одна роль сохранила users.manage
    engine = make_engine(app.state.settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            holders = set(
                await s.scalars(
                    select(RolePermission.role_id).where(
                        RolePermission.permission == "users.manage"
                    )
                )
            )
    finally:
        await engine.dispose()
    assert len(holders) == 1
    for c in clients:
        await c.aclose()


async def test_two_admins_cannot_block_each_other_concurrently(
    real_app: FastAPI,
    race_barrier: None,
) -> None:
    app = real_app
    clients: list[httpx.AsyncClient] = []
    user_ids: list[int] = []
    engine = make_engine(app.state.settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            role = await create_role(s, "Админ", "users.manage")
            for n in (1, 2):
                user = await create_user(s, role, f"admin{n}", "password-1")
                user_ids.append(user.id)
    finally:
        await engine.dispose()
    for n in (1, 2):
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"X-Requested-With": "rs"},
        )
        assert (
            await c.post("/api/auth/login", json={"login": f"admin{n}", "password": "password-1"})
        ).status_code == 200
        clients.append(c)

    responses = await asyncio.gather(
        clients[0].post(f"/api/admin/users/{user_ids[1]}/block"),
        clients[1].post(f"/api/admin/users/{user_ids[0]}/block"),
    )
    # Первый блокировщик успевает, второй уже заблокирован (401) или упирается в инвариант (409)
    statuses = sorted(r.status_code for r in responses)
    assert statuses[0] == 200 and statuses[1] in (401, 409), [r.text for r in responses]
    for c in clients:
        await c.aclose()
