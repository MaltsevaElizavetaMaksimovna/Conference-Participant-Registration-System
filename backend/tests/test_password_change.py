"""Смена своего пароля: `PUT /api/auth/me/password` (S-02)."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import token_hash, verify_password
from app.models.staff import StaffSession, StaffUser
from tests.conftest import LoginAs

URL = "/api/auth/me/password"
NEW = "brand-new-pass"


async def _revoked(db: AsyncSession, token: str) -> bool:
    db.expunge_all()
    value = await db.scalar(
        select(StaffSession.revoked_at).where(StaffSession.id == token_hash(token))
    )
    return value is not None


async def test_change_password_keeps_current_session_and_ends_others(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    c = await login_as()  # сотрудник без разрешений: достаточно сессии
    other = await anon.post("/api/auth/login", json={"login": c.login, "password": c.password})
    assert other.status_code == 200
    other_token = anon.cookies["rs_session"]

    r = await c.put(URL, json={"current_password": c.password, "new_password": NEW})
    assert r.status_code == 204, r.text
    assert r.content == b""

    assert (await c.get("/api/auth/me")).status_code == 200  # текущая сессия жива
    assert await _revoked(db, other_token)
    assert (await anon.get("/api/auth/me")).status_code == 401  # остальные завершены

    db.expunge_all()
    user = await db.get(StaffUser, c.user_id)
    assert user is not None
    assert verify_password(user.password_hash, NEW)
    assert not verify_password(user.password_hash, c.password)

    # входить теперь можно только с новым паролем
    bad = await anon.post("/api/auth/login", json={"login": c.login, "password": c.password})
    assert bad.status_code == 401
    ok = await anon.post("/api/auth/login", json={"login": c.login, "password": NEW})
    assert ok.status_code == 200


async def test_wrong_current_password_is_401_and_changes_nothing(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as()
    r = await c.put(URL, json={"current_password": "not-my-password", "new_password": NEW})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"
    assert (await c.get("/api/auth/me")).status_code == 200  # сессия цела
    db.expunge_all()
    user = await db.get(StaffUser, c.user_id)
    assert user is not None and verify_password(user.password_hash, c.password)


async def test_new_password_must_have_8_characters(login_as: LoginAs) -> None:
    c = await login_as()
    r = await c.put(URL, json={"current_password": c.password, "new_password": "short"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"
    assert "new_password" in r.json()["details"]["fields"]
    r = await c.put(URL, json={"current_password": c.password, "new_password": "12345678"})
    assert r.status_code == 204  # ровно 8 символов допустимо


async def test_wrong_attempts_share_the_login_rate_limit(login_as: LoginAs) -> None:
    c = await login_as()
    body = {"current_password": "nope-nope-nope", "new_password": NEW}
    for _ in range(10):
        assert (await c.put(URL, json=body)).status_code == 401
    r = await c.put(URL, json=body)
    assert r.status_code == 429
    assert r.json()["code"] == "too_many_requests"
    # и верный пароль в этот момент не принимается
    r = await c.put(URL, json={"current_password": c.password, "new_password": NEW})
    assert r.status_code == 429


async def test_requires_session_and_csrf(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    body = {"current_password": "password-1", "new_password": NEW}
    r = await anon.put(URL, json=body, headers={"X-Requested-With": "rs"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"
    c = await login_as()
    del c.headers["X-Requested-With"]
    r = await c.put(URL, json=body)
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_required"
