"""Вход и сессии сотрудников (B1-01): RG-01 и блокировка из AD-03."""

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.core.config import Settings
from app.core.security import token_hash
from app.models.base import utcnow
from app.models.device import Printer
from app.models.staff import StaffSession, StaffUser
from tests.conftest import LoginAs, create_role, create_user

REGISTRAR = ("participants.view", "registration.desk", "stickers.print")


async def _make_user(db: AsyncSession, *, blocked: bool = False) -> StaffUser:
    role = await create_role(db, None, *REGISTRAR)
    return await create_user(db, role, "Reg.One", "correct-password", blocked=blocked)


# ------------------------------------------------------------------ вход


async def test_login_success_sets_cookie_and_returns_profile(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = await _make_user(db)
    r = await anon.post(
        "/api/auth/login", json={"login": "Reg.One", "password": "correct-password"}
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["id"] == user.id
    assert me["login"] == "Reg.One"
    assert me["role"]["id"] == user.role_id
    assert me["permissions"] == list(REGISTRAR)
    assert me["panel_printer_id"] is None

    cookie = r.headers["set-cookie"]
    assert cookie.startswith("rs_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert f"Max-Age={12 * 3600}" in cookie
    assert "Secure" not in cookie  # не prod

    token = anon.cookies["rs_session"]
    sess = (
        await db.execute(select(StaffSession).where(StaffSession.id == token_hash(token)))
    ).scalar_one()
    assert sess.id != token  # в БД только sha256 токена
    assert sess.user_id == user.id
    assert sess.permissions == list(REGISTRAR)
    assert sess.revoked_at is None
    ttl = sess.expires_at - sess.created_at
    assert timedelta(hours=12) - timedelta(seconds=5) <= ttl <= timedelta(hours=12, seconds=5)


async def test_login_is_case_insensitive_and_trims(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    await _make_user(db)
    r = await anon.post(
        "/api/auth/login", json={"login": "  rEG.oNE ", "password": "correct-password"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["login"] == "Reg.One"


async def test_password_is_stored_as_argon2_hash(db: AsyncSession) -> None:
    user = await _make_user(db)
    assert user.password_hash.startswith("$argon2id$")
    assert "correct-password" not in user.password_hash


async def test_session_ttl_comes_from_settings(
    anon: httpx.AsyncClient, app_db: FastAPI, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _make_user(db)
    monkeypatch.setattr(app_db.state.settings, "session_ttl_hours", 1)
    r = await anon.post(
        "/api/auth/login", json={"login": "reg.one", "password": "correct-password"}
    )
    assert f"Max-Age={3600}" in r.headers["set-cookie"]
    expires = await db.scalar(
        select(StaffSession.expires_at - StaffSession.created_at).order_by(
            StaffSession.created_at.desc()
        )
    )
    assert expires == timedelta(hours=1)


async def test_cookie_is_secure_in_prod(
    anon: httpx.AsyncClient, app_db: FastAPI, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _make_user(db)
    monkeypatch.setattr(app_db.state.settings, "env", "prod")
    r = await anon.post(
        "/api/auth/login", json={"login": "reg.one", "password": "correct-password"}
    )
    assert "Secure" in r.headers["set-cookie"]


@pytest.mark.parametrize(
    ("login", "password"),
    [("Reg.One", "wrong-password"), ("nobody", "correct-password")],
    ids=["wrong_password", "unknown_login"],
)
async def test_invalid_credentials(
    anon: httpx.AsyncClient, db: AsyncSession, login: str, password: str
) -> None:
    await _make_user(db)
    r = await anon.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"
    assert r.json()["message"] == "Неверный логин или пароль"
    assert "set-cookie" not in r.headers


async def test_unknown_login_still_verifies_a_password(
    anon: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Для неизвестного логина считается argon2 по фиктивному хэшу (одинаковое время ответа)."""
    await _make_user(db)
    calls: list[str] = []
    real = service.verify_password

    def spy(password_hash: str, password: str) -> bool:
        calls.append(password_hash)
        return real(password_hash, password)

    monkeypatch.setattr(service, "verify_password", spy)
    await anon.post("/api/auth/login", json={"login": "nobody", "password": "x"})
    assert len(calls) == 1
    assert calls[0].startswith("$argon2")


async def test_blocked_user_cannot_log_in(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await _make_user(db, blocked=True)
    r = await anon.post(
        "/api/auth/login", json={"login": "Reg.One", "password": "correct-password"}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "user_blocked"
    assert r.json()["message"] == "Учётная запись заблокирована"
    assert "set-cookie" not in r.headers
    assert await db.scalar(select(StaffSession.id).limit(1)) is None


async def test_blocked_status_is_not_revealed_for_wrong_password(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    await _make_user(db, blocked=True)
    r = await anon.post("/api/auth/login", json={"login": "Reg.One", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_login_validation(anon: httpx.AsyncClient) -> None:
    r = await anon.post("/api/auth/login", json={"login": "", "password": ""})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_login_rehashes_outdated_password_hash(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    from argon2 import PasswordHasher

    user = await _make_user(db)
    old = PasswordHasher(time_cost=1, memory_cost=16, parallelism=1).hash("correct-password")
    await db.execute(update(StaffUser).where(StaffUser.id == user.id).values(password_hash=old))
    await db.commit()
    r = await anon.post(
        "/api/auth/login", json={"login": "Reg.One", "password": "correct-password"}
    )
    assert r.status_code == 200
    new = await db.scalar(select(StaffUser.password_hash).where(StaffUser.id == user.id))
    assert new != old


# ------------------------------------------------------- ограничение перебора


async def test_login_rate_limit(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await _make_user(db)
    bad = {"login": "Reg.One", "password": "wrong-password"}
    for _ in range(10):
        r = await anon.post("/api/auth/login", json=bad)
        assert r.status_code == 401
    r = await anon.post("/api/auth/login", json=bad)
    assert r.status_code == 429
    assert r.json()["code"] == "too_many_requests"
    assert r.json()["details"]["retry_after_s"] > 0
    # Пока действует блокировка, и верный пароль не пускает
    r = await anon.post(
        "/api/auth/login", json={"login": "reg.one", "password": "correct-password"}
    )
    assert r.status_code == 429
    # Другой логин с того же адреса не затронут
    r = await anon.post("/api/auth/login", json={"login": "someone-else", "password": "x"})
    assert r.status_code == 401


async def test_successful_login_resets_failures(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await _make_user(db)
    bad = {"login": "Reg.One", "password": "wrong-password"}
    for _ in range(9):
        assert (await anon.post("/api/auth/login", json=bad)).status_code == 401
    ok = {"login": "Reg.One", "password": "correct-password"}
    assert (await anon.post("/api/auth/login", json=ok)).status_code == 200
    for _ in range(9):
        assert (await anon.post("/api/auth/login", json=bad)).status_code == 401


async def test_rate_limit_window_expires() -> None:
    from app.auth.ratelimit import LoginRateLimiter

    now = [0.0]
    limiter = LoginRateLimiter(3, 300, clock=lambda: now[0])
    key = ("1.2.3.4", "reg")
    for _ in range(3):
        assert limiter.retry_after(key) is None
        limiter.fail(key)
    assert limiter.retry_after(key) is not None
    now[0] = 301
    assert limiter.retry_after(key) is None


# ------------------------------------------------------------ сессия и /me


async def test_me_requires_login(anon: httpx.AsyncClient) -> None:
    r = await anon.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"
    assert r.json()["message"] == "Требуется вход в систему"


async def test_me_with_garbage_cookie(anon: httpx.AsyncClient) -> None:
    anon.cookies.set("rs_session", "not-a-real-token")
    r = await anon.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"


async def test_me_returns_profile(login_as: LoginAs) -> None:
    c = await login_as(*REGISTRAR, login="reg1")
    r = await c.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == c.user_id
    assert body["login"] == "reg1"
    assert body["permissions"] == list(REGISTRAR)


async def test_logout_revokes_session(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as(*REGISTRAR)
    token = c.cookies["rs_session"]
    r = await c.post("/api/auth/logout")
    assert r.status_code == 204
    assert "rs_session=" in r.headers["set-cookie"]
    assert "Max-Age=0" in r.headers["set-cookie"]
    revoked = await db.scalar(
        select(StaffSession.revoked_at).where(StaffSession.id == token_hash(token))
    )
    assert revoked is not None
    # Старый токен больше не работает, даже если его вернуть в cookie
    c.cookies.set("rs_session", token)
    r = await c.get("/api/auth/me")
    assert r.status_code == 401


async def test_logout_without_session_is_401(anon: httpx.AsyncClient) -> None:
    r = await anon.post("/api/auth/logout", headers={"X-Requested-With": "rs"})
    assert r.status_code == 401


async def test_expired_session_requires_new_login(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as(*REGISTRAR)
    assert (await c.get("/api/auth/me")).status_code == 200
    await db.execute(
        update(StaffSession)
        .where(StaffSession.user_id == c.user_id)
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    await db.commit()
    r = await c.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"
    # Повторный вход создаёт новую сессию
    r = await c.post("/api/auth/login", json={"login": c.login, "password": c.password})
    assert r.status_code == 200
    assert (await c.get("/api/auth/me")).status_code == 200


async def test_blocked_user_session_stops_working(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as(*REGISTRAR)
    await db.execute(update(StaffUser).where(StaffUser.id == c.user_id).values(is_blocked=True))
    await db.commit()
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_last_seen_is_updated_at_most_once_a_minute(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as(*REGISTRAR)

    async def last_seen() -> object:
        return await db.scalar(
            select(StaffSession.last_seen_at).where(StaffSession.user_id == c.user_id)
        )

    first = await last_seen()
    await c.get("/api/auth/me")
    assert await last_seen() == first  # прошло меньше минуты

    old = utcnow() - timedelta(minutes=5)
    await db.execute(
        update(StaffSession).where(StaffSession.user_id == c.user_id).values(last_seen_at=old)
    )
    await db.commit()
    await c.get("/api/auth/me")
    assert await last_seen() > old  # type: ignore[operator]


# ------------------------------------------------------------------- CSRF


async def test_csrf_header_is_required_for_writes(login_as: LoginAs) -> None:
    c = await login_as(*REGISTRAR)
    del c.headers["X-Requested-With"]
    r = await c.put("/api/auth/me/printer", json={"printer_id": None})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_required"
    r = await c.post("/api/auth/logout")
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_required"
    r = await c.put(
        "/api/auth/me/printer", json={"printer_id": None}, headers={"X-Requested-With": "x"}
    )
    assert r.json()["code"] == "csrf_required"
    # Чтение CSRF-заголовка не требует
    assert (await c.get("/api/auth/me")).status_code == 200
    # С заголовком запись проходит
    r = await c.put(
        "/api/auth/me/printer", json={"printer_id": None}, headers={"X-Requested-With": "rs"}
    )
    assert r.status_code == 200


async def test_anonymous_write_is_401_not_csrf(anon: httpx.AsyncClient) -> None:
    r = await anon.put("/api/auth/me/printer", json={"printer_id": None})
    assert r.status_code == 401


# --------------------------------------------------------- принтер панели


async def test_panel_printer(login_as: LoginAs, db: AsyncSession) -> None:
    printer = Printer(name="Принтер для теста")
    db.add(printer)
    await db.commit()
    c = await login_as(*REGISTRAR)

    r = await c.put("/api/auth/me/printer", json={"printer_id": printer.id})
    assert r.status_code == 200, r.text
    assert r.json()["panel_printer_id"] == printer.id
    assert (await c.get("/api/auth/me")).json()["panel_printer_id"] == printer.id

    r = await c.put("/api/auth/me/printer", json={"printer_id": None})
    assert r.status_code == 200
    assert r.json()["panel_printer_id"] is None


async def test_panel_printer_not_found(login_as: LoginAs) -> None:
    c = await login_as(*REGISTRAR)
    r = await c.put("/api/auth/me/printer", json={"printer_id": 987654})
    assert r.status_code == 404
    assert r.json()["code"] == "printer_not_found"


async def test_panel_printer_needs_stickers_print(login_as: LoginAs) -> None:
    c = await login_as("participants.view")
    r = await c.put("/api/auth/me/printer", json={"printer_id": None})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert (await c.get("/api/auth/me")).status_code == 200  # /me доступен любой сессии


def test_settings_defaults() -> None:
    s = Settings()
    assert s.session_ttl_hours == 12
    assert s.login_max_failures == 10
    assert s.login_fail_window_s == 300
