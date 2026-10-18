"""Вход, выход и профиль сотрудника (RG-01, AD-03, AD-04, RG-05)."""

import asyncio
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ratelimit import LoginRateLimiter
from app.auth.schemas import MeOut
from app.core.config import Settings
from app.core.errors import AppError
from app.core.permissions import Permission
from app.core.security import (
    dummy_hash,
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    verify_password,
)
from app.models.base import utcnow
from app.models.device import Printer
from app.models.staff import Role, RolePermission, StaffSession, StaffUser
from app.roles.schemas import RoleRef

# Просроченные и отозванные сессии пользователя удаляются при его следующем входе
_STALE_SESSION_AGE = timedelta(days=1)


def sort_permissions(codes: set[str] | frozenset[str] | list[str]) -> list[str]:
    """Коды разрешений в порядке каталога (неизвестные отбрасываются)."""
    have = set(codes)
    return [str(p) for p in Permission if str(p) in have]


async def role_permissions(session: AsyncSession, role_id: int) -> list[str]:
    codes = await session.scalars(
        select(RolePermission.permission).where(RolePermission.role_id == role_id)
    )
    return sort_permissions(set(codes))


async def build_me(session: AsyncSession, user: StaffUser, permissions: list[str]) -> MeOut:
    role = await session.get(Role, user.role_id)
    assert role is not None  # role_id NOT NULL + FK
    return MeOut(
        id=user.id,
        full_name=user.full_name,
        login=user.login,
        role=RoleRef(id=role.id, name=role.name),
        permissions=permissions,  # type: ignore[arg-type]  # str -> Literal PermissionCode
        panel_printer_id=user.panel_printer_id,
    )


async def authenticate(
    session: AsyncSession,
    settings: Settings,
    limiter: LoginRateLimiter,
    *,
    login: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, MeOut]:
    """Проверяет логин и пароль, заводит серверную сессию. Возвращает (токен cookie, профиль)."""
    login = login.strip()
    key = (ip or "-", login.casefold())

    retry_after = limiter.retry_after(key)
    if retry_after is not None:
        raise AppError(
            "too_many_requests",
            "Слишком много неудачных попыток входа. Повторите позже",
            429,
            {"retry_after_s": retry_after},
        )

    user = await session.scalar(
        select(StaffUser).where(func.lower(StaffUser.login) == func.lower(login))
    )
    # Для неизвестного логина всё равно считаем argon2: время ответа не выдаёт, что логина нет
    hashed = user.password_hash if user is not None else dummy_hash()
    password_ok = await asyncio.to_thread(verify_password, hashed, password)
    if user is None or not password_ok:
        limiter.fail(key)
        raise AppError("invalid_credentials", "Неверный логин или пароль", 401)
    if user.is_blocked:
        raise AppError("user_blocked", "Учётная запись заблокирована", 403)
    limiter.reset(key)

    if await asyncio.to_thread(needs_rehash, user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, password)

    permissions = await role_permissions(session, user.role_id)
    now = utcnow()
    token = new_token()
    await session.execute(
        delete(StaffSession).where(
            StaffSession.user_id == user.id,
            (StaffSession.expires_at < now - _STALE_SESSION_AGE)
            | (StaffSession.revoked_at < now - _STALE_SESSION_AGE),
        )
    )
    session.add(
        StaffSession(
            id=token_hash(token),
            user_id=user.id,
            permissions=permissions,
            created_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            last_seen_at=now,
            ip=ip,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    await session.commit()
    return token, await build_me(session, user, permissions)


async def revoke_session(session: AsyncSession, session_id: str) -> None:
    await session.execute(
        update(StaffSession)
        .where(StaffSession.id == session_id, StaffSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await session.commit()


async def current_profile(session: AsyncSession, user_id: int, permissions: list[str]) -> MeOut:
    user = await session.get(StaffUser, user_id)
    if user is None:  # сессия есть, а пользователя нет — быть не должно (FK)
        raise AppError("unauthenticated", "Требуется вход в систему", 401)
    return await build_me(session, user, permissions)


async def set_panel_printer(session: AsyncSession, user_id: int, printer_id: int | None) -> None:
    if printer_id is not None and await session.get(Printer, printer_id) is None:
        raise AppError("printer_not_found", "Принтер не найден", 404)
    await session.execute(
        update(StaffUser).where(StaffUser.id == user_id).values(panel_printer_id=printer_id)
    )
    await session.commit()
