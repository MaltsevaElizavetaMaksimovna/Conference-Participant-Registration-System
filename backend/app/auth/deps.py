"""Текущий сотрудник и проверка разрешений — общий интерфейс для всех модулей.

Остальные модули импортируют только `CurrentStaff`, `get_current_staff` и `require_staff`.
В тестах сотрудник подменяется через `app.dependency_overrides[get_current_staff]`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.permissions import Permission
from app.core.security import token_hash
from app.models.base import utcnow
from app.models.staff import StaffSession, StaffUser

SESSION_COOKIE = "rs_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "rs"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# last_seen_at обновляется не чаще раза в минуту, чтобы не писать в БД на каждый запрос
LAST_SEEN_INTERVAL = timedelta(minutes=1)
_MAX_TOKEN_LEN = 256


@dataclass(frozen=True)
class CurrentStaff:
    user_id: int
    login: str
    full_name: str
    role_id: int
    permissions: frozenset[Permission]
    session_id: str

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


def unauthenticated() -> AppError:
    return AppError("unauthenticated", "Требуется вход в систему", 401)


def check_csrf(request: Request) -> None:
    """Запросы, меняющие данные, должны нести `X-Requested-With: rs` (защита от CSRF)."""
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AppError(
            "csrf_required",
            "Не хватает заголовка X-Requested-With: rs",
            403,
        )


async def get_current_staff(
    request: Request, session: AsyncSession = Depends(get_session)
) -> CurrentStaff:
    """Сотрудник по cookie `rs_session`.

    Сессия должна быть найдена, не отозвана и не истекла, а пользователь — не заблокирован,
    иначе `401 unauthenticated`. Права берутся из снимка сессии (AD-04: правки роли действуют
    со следующего входа). Для методов, меняющих данные, нужен CSRF-заголовок.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > _MAX_TOKEN_LEN:
        raise unauthenticated()

    row = (
        await session.execute(
            select(StaffSession, StaffUser)
            .join(StaffUser, StaffUser.id == StaffSession.user_id)
            .where(StaffSession.id == token_hash(token))
        )
    ).first()
    now = utcnow()
    if row is None:
        raise unauthenticated()
    sess, user = row
    if sess.revoked_at is not None or sess.expires_at <= now or user.is_blocked:
        raise unauthenticated()

    check_csrf(request)

    if now - sess.last_seen_at >= LAST_SEEN_INTERVAL:
        await session.execute(
            update(StaffSession).where(StaffSession.id == sess.id).values(last_seen_at=now)
        )
        await session.commit()

    known = {str(p) for p in Permission}
    return CurrentStaff(
        user_id=user.id,
        login=user.login,
        full_name=user.full_name,
        role_id=user.role_id,
        permissions=frozenset(Permission(p) for p in sess.permissions if p in known),
        session_id=sess.id,
    )


def require_staff(*permissions: Permission) -> Callable[..., Awaitable[CurrentStaff]]:
    """Зависимость: сотрудник со всеми перечисленными разрешениями, иначе 403 forbidden."""

    async def dependency(staff: CurrentStaff = Depends(get_current_staff)) -> CurrentStaff:
        missing = [p for p in permissions if not staff.has(p)]
        if missing:
            raise AppError(
                "forbidden", "Недостаточно прав", 403, {"missing": [str(p) for p in missing]}
            )
        return staff

    return dependency
