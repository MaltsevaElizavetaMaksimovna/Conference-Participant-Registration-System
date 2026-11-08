"""Учётные записи сотрудников (B1-03, AD-03)."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.staff import StaffSession, StaffUser
from tests.conftest import LoginAs, create_role, create_user

NEW_USER = {
    "full_name": "Смирнова Елена Викторовна",
    "login": "reg1",
    "password": "S3cret-pass",
}


async def _login(client: httpx.AsyncClient, login: str, password: str) -> httpx.Response:
    return await client.post("/api/auth/login", json={"login": login, "password": password})


# ---------------------------------------------------------------- создание


async def test_admin_creates_user_who_can_log_in(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    """AD-03: учётку создаёт администратор (ФИО, логин, пароль, роль)."""
    admin = await login_as("users.manage")
    role = await create_role(db, "Регистратор", "participants.view", "registration.desk")

    r = await admin.post("/api/admin/users", json={**NEW_USER, "role_id": role.id})
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["full_name"] == NEW_USER["full_name"]
    assert user["login"] == "reg1"
    assert user["role"] == {"id": role.id, "name": "Регистратор"}
    assert user["is_blocked"] is False
    assert "password" not in user and "password_hash" not in user
    assert user["created_at"]

    stored = await db.scalar(select(StaffUser.password_hash).where(StaffUser.id == user["id"]))
    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, NEW_USER["password"])

    r = await _login(anon, "reg1", NEW_USER["password"])
    assert r.status_code == 200
    assert r.json()["permissions"] == ["participants.view", "registration.desk"]


async def test_login_must_be_unique_ignoring_case(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage", login="Admin.One")
    role = await create_role(db, None, "participants.view")
    r = await admin.post(
        "/api/admin/users", json={**NEW_USER, "login": "ADMIN.one", "role_id": role.id}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "login_taken"
    assert (
        await admin.post("/api/admin/users", json={**NEW_USER, "role_id": role.id})
    ).status_code == 201
    r = await admin.post("/api/admin/users", json={**NEW_USER, "login": "Reg1", "role_id": role.id})
    assert r.status_code == 409
    assert r.json()["code"] == "login_taken"


async def test_password_must_have_at_least_8_characters(
    login_as: LoginAs, db: AsyncSession
) -> None:
    admin = await login_as("users.manage")
    role = await create_role(db, None, "participants.view")
    r = await admin.post(
        "/api/admin/users", json={**NEW_USER, "password": "1234567", "role_id": role.id}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"
    assert r.json()["details"]["fields"]["password"] == "Пароль должен быть не короче 8 символов"
    r = await admin.post(
        "/api/admin/users", json={**NEW_USER, "password": "12345678", "role_id": role.id}
    )
    assert r.status_code == 201


async def test_create_user_validation(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    role = await create_role(db, None, "participants.view")
    r = await admin.post(
        "/api/admin/users", json={**NEW_USER, "full_name": "   ", "role_id": role.id}
    )
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["full_name"] == "Укажите ФИО"
    r = await admin.post("/api/admin/users", json={**NEW_USER, "login": "  ", "role_id": role.id})
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["login"] == "Укажите логин"
    r = await admin.post("/api/admin/users", json={"full_name": "X"})
    assert r.status_code == 422


async def test_create_user_with_unknown_role(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.post("/api/admin/users", json={**NEW_USER, "role_id": 987654})
    assert r.status_code == 404
    assert r.json()["code"] == "role_not_found"


async def test_login_is_trimmed_on_create(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    role = await create_role(db, None, "participants.view")
    r = await admin.post(
        "/api/admin/users", json={**NEW_USER, "login": "  reg1  ", "role_id": role.id}
    )
    assert r.json()["login"] == "reg1"


# ----------------------------------------------------------------- список


async def test_list_users(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage", login="boss")
    role = await create_role(db, None, "participants.view")
    for n in range(3):
        await create_user(db, role, f"reg{n}")
    r = await admin.get("/api/admin/users")
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 4
    assert [u["login"] for u in page["items"]] == ["boss", "reg0", "reg1", "reg2"]
    assert page["items"][0]["role"]["id"] == admin.role_id

    r = await admin.get("/api/admin/users", params={"limit": 2, "offset": 2})
    assert [u["login"] for u in r.json()["items"]] == ["reg1", "reg2"]
    assert r.json()["total"] == 4


# ------------------------------------------------------------- изменение


async def test_update_name_and_role_apply_from_next_login(
    login_as: LoginAs, db: AsyncSession
) -> None:
    admin = await login_as("users.manage")
    old = await create_role(db, None, "participants.view")
    new = await create_role(db, None, "participants.view", "imports.run")
    reg = await login_as(role=old)

    r = await admin.put(
        f"/api/admin/users/{reg.user_id}", json={"full_name": "  Новое   Имя ", "role_id": new.id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Новое Имя"
    assert r.json()["role"]["id"] == new.id

    assert (await reg.get("/api/admin/import-template.xlsx")).status_code == 403  # сессия прежняя
    await _login(reg, reg.login, reg.password)
    assert (await reg.get("/api/admin/import-template.xlsx")).status_code == 200
    assert (await reg.get("/api/auth/me")).json()["full_name"] == "Новое Имя"


async def test_update_with_empty_body_changes_nothing(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.put(f"/api/admin/users/{admin.user_id}", json={})
    assert r.status_code == 200
    assert r.json()["role"]["id"] == admin.role_id


async def test_update_unknown_user_and_role(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.put("/api/admin/users/987654", json={"full_name": "X"})
    assert r.status_code == 404
    assert r.json()["code"] == "user_not_found"
    r = await admin.put(f"/api/admin/users/{admin.user_id}", json={"role_id": 987654})
    assert r.status_code == 404
    assert r.json()["code"] == "role_not_found"


async def test_password_change(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    admin = await login_as("users.manage")
    reg = await login_as("participants.view", login="victim", password="old-password")

    r = await admin.put(f"/api/admin/users/{reg.user_id}", json={"password": "short"})
    assert r.status_code == 422

    r = await admin.put(f"/api/admin/users/{reg.user_id}", json={"password": "brand-new-pass"})
    assert r.status_code == 200
    assert "password" not in r.json()
    assert (await _login(anon, "victim", "old-password")).status_code == 401
    assert (await _login(anon, "victim", "brand-new-pass")).status_code == 200
    # Старая сессия сотрудника после смены пароля завершена
    assert (await reg.get("/api/auth/me")).status_code == 401


async def test_admin_changing_own_password_keeps_own_session(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    r = await admin.put(f"/api/admin/users/{admin.user_id}", json={"password": "my-new-password"})
    assert r.status_code == 200
    assert (await admin.get("/api/auth/me")).status_code == 200


async def test_sole_admin_role_cannot_be_changed_away(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    plain = await create_role(db, None, "participants.view")
    r = await admin.put(f"/api/admin/users/{admin.user_id}", json={"role_id": plain.id})
    assert r.status_code == 409
    assert r.json()["code"] == "last_admin_permission"
    me = await admin.get("/api/auth/me")  # роль не изменилась
    assert me.json()["role"]["id"] == admin.role_id
    row = await db.scalar(select(StaffUser.role_id).where(StaffUser.id == admin.user_id))
    assert row == admin.role_id
    # Если есть второй действующий администратор — можно
    second = await login_as("users.manage")
    r = await admin.put(f"/api/admin/users/{admin.user_id}", json={"role_id": plain.id})
    assert r.status_code == 200
    # ...а теперь второй — единственный
    r = await second.put(f"/api/admin/users/{second.user_id}", json={"role_id": plain.id})
    assert r.status_code == 409


# ---------------------------------------------------------- блокировка


async def test_block_revokes_sessions_and_forbids_login(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    """AD-03: заблокированный не может войти — «Учётная запись заблокирована»."""
    admin = await login_as("users.manage")
    reg = await login_as("participants.view", login="reg1", password="reg-password")
    assert (await _login(anon, "reg1", "reg-password")).status_code == 200  # вторая сессия
    assert (await reg.get("/api/auth/me")).status_code == 200

    r = await admin.post(f"/api/admin/users/{reg.user_id}/block")
    assert r.status_code == 200, r.text
    assert r.json()["is_blocked"] is True

    assert (await reg.get("/api/auth/me")).status_code == 401  # сессия отозвана
    assert (await anon.get("/api/auth/me")).status_code == 401  # и вторая тоже
    active = await db.scalars(
        select(StaffSession.id).where(
            StaffSession.user_id == reg.user_id, StaffSession.revoked_at.is_(None)
        )
    )
    assert list(active) == []

    r = await _login(anon, "reg1", "reg-password")
    assert r.status_code == 403
    assert r.json()["code"] == "user_blocked"
    assert r.json()["message"] == "Учётная запись заблокирована"


async def test_unblock_allows_login_again(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    admin = await login_as("users.manage")
    reg = await login_as("participants.view", login="reg1", password="reg-password")
    await admin.post(f"/api/admin/users/{reg.user_id}/block")
    r = await admin.post(f"/api/admin/users/{reg.user_id}/unblock")
    assert r.status_code == 200
    assert r.json()["is_blocked"] is False
    assert (await _login(anon, "reg1", "reg-password")).status_code == 200


async def test_block_and_unblock_are_idempotent(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    reg = await login_as("participants.view")
    for _ in range(2):
        assert (await admin.post(f"/api/admin/users/{reg.user_id}/block")).json()["is_blocked"]
    for _ in range(2):
        assert not (await admin.post(f"/api/admin/users/{reg.user_id}/unblock")).json()[
            "is_blocked"
        ]


async def test_block_unknown_user(login_as: LoginAs) -> None:
    admin = await login_as("users.manage")
    for action in ("block", "unblock"):
        r = await admin.post(f"/api/admin/users/987654/{action}")
        assert r.status_code == 404
        assert r.json()["code"] == "user_not_found"


async def test_sole_admin_cannot_be_blocked(login_as: LoginAs, db: AsyncSession) -> None:
    admin = await login_as("users.manage")
    r = await admin.post(f"/api/admin/users/{admin.user_id}/block")
    assert r.status_code == 409
    assert r.json()["code"] == "last_admin_permission"
    assert (await admin.get("/api/auth/me")).status_code == 200  # не заблокирован, сессия жива
    assert (
        await db.scalar(select(StaffUser.is_blocked).where(StaffUser.id == admin.user_id)) is False
    )


async def test_admin_can_block_another_admin_but_not_the_last(login_as: LoginAs) -> None:
    first = await login_as("users.manage")
    second = await login_as("users.manage")
    assert (await first.post(f"/api/admin/users/{second.user_id}/block")).status_code == 200
    r = await first.post(f"/api/admin/users/{first.user_id}/block")
    assert r.status_code == 409
    assert r.json()["code"] == "last_admin_permission"
    # Разблокировали — снова можно заблокировать себя
    await first.post(f"/api/admin/users/{second.user_id}/unblock")
    assert (await first.post(f"/api/admin/users/{first.user_id}/block")).status_code == 200
    assert (await first.get("/api/auth/me")).status_code == 401  # заблокировал себя -> вышел
