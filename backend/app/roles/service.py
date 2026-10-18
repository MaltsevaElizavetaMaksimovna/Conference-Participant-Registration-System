"""Роли, разрешения и учётные записи сотрудников (AD-03, AD-04).

Инвариант «в системе остаётся администратор»: хотя бы у одной действующей (не заблокированной)
учётной записи есть разрешение `users.manage`. Он проверяется внутри транзакции после
изменения, а при нарушении транзакция откатывается. Все операции, которые могут нарушить
инвариант или зависят от него, берут один транзакционный advisory-lock (`lock_staff_admin`),
поэтому две одновременные правки не обходят проверку (гонка «двое администраторов
одновременно лишают друг друга прав»).
"""

import asyncio
from collections.abc import Collection
from typing import cast

from sqlalchemy import (
    ColumnElement,
    delete,
    exists,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.permissions import PERMISSION_TITLES, Permission
from app.core.security import hash_password
from app.models.base import utcnow
from app.models.staff import Role, RolePermission, StaffSession, StaffUser
from app.roles.schemas import (
    PermissionCode,
    PermissionOut,
    RoleIn,
    RoleOut,
    RoleRef,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)

# Ключ advisory-lock для правок ролей и учётных записей (произвольная константа проекта)
_STAFF_ADMIN_LOCK = 0x52_53_41_44  # "RSAD"

ROLE_IN_USE_MESSAGE = "Роль назначена сотрудникам — сначала смените им роль"
LAST_ADMIN_MESSAGE = (
    "Нельзя оставить систему без администратора: у одной действующей учётной записи "
    "должно остаться разрешение «Управление учётными записями и ролями»"
)


# --------------------------------------------------------------------------- общее


def sort_permissions(codes: Collection[str]) -> list[str]:
    """Коды разрешений в порядке каталога; неизвестные коды отбрасываются."""
    have = set(codes)
    return [str(p) for p in Permission if str(p) in have]


def as_codes(codes: list[str]) -> list[PermissionCode]:
    return cast(list[PermissionCode], codes)


async def role_permissions(session: AsyncSession, role_id: int) -> list[str]:
    codes = await session.scalars(
        select(RolePermission.permission).where(RolePermission.role_id == role_id)
    )
    return sort_permissions(set(codes))


async def lock_staff_admin(session: AsyncSession) -> None:
    """Сериализует правки ролей и сотрудников до конца транзакции."""
    await session.execute(select(func.pg_advisory_xact_lock(_STAFF_ADMIN_LOCK)))


def _active_admin_exists() -> ColumnElement[bool]:
    return exists().where(
        StaffUser.role_id == RolePermission.role_id,
        RolePermission.permission == str(Permission.USERS_MANAGE),
        StaffUser.is_blocked.is_(False),
    )


async def ensure_admin_remains(session: AsyncSession) -> None:
    """Если после правки не осталось действующего администратора — откат и 409."""
    if not await session.scalar(select(_active_admin_exists())):
        await session.rollback()
        raise AppError("last_admin_permission", LAST_ADMIN_MESSAGE, 409)


def permissions_catalog() -> list[PermissionOut]:
    return [
        PermissionOut(code=cast(PermissionCode, str(p)), title=t)
        for p, t in PERMISSION_TITLES.items()
    ]


# --------------------------------------------------------------------------- роли


def _role_not_found() -> AppError:
    return AppError("role_not_found", "Роль не найдена", 404)


async def _users_counts(session: AsyncSession, role_ids: list[int]) -> dict[int, int]:
    rows = await session.execute(
        select(StaffUser.role_id, func.count())
        .where(StaffUser.role_id.in_(role_ids))
        .group_by(StaffUser.role_id)
    )
    return {role_id: count for role_id, count in rows}


async def _role_out(session: AsyncSession, role: Role) -> RoleOut:
    counts = await _users_counts(session, [role.id])
    return RoleOut(
        id=role.id,
        name=role.name,
        is_system=role.is_system,
        permissions=as_codes(await role_permissions(session, role.id)),
        users_count=counts.get(role.id, 0),
    )


async def list_roles(session: AsyncSession, limit: int, offset: int) -> tuple[list[RoleOut], int]:
    total = await session.scalar(select(func.count()).select_from(Role)) or 0
    roles = list(await session.scalars(select(Role).order_by(Role.id).limit(limit).offset(offset)))
    ids = [r.id for r in roles]
    counts = await _users_counts(session, ids)
    perms: dict[int, set[str]] = {i: set() for i in ids}
    for role_id, code in await session.execute(
        select(RolePermission.role_id, RolePermission.permission).where(
            RolePermission.role_id.in_(ids)
        )
    ):
        perms[role_id].add(code)
    items = [
        RoleOut(
            id=r.id,
            name=r.name,
            is_system=r.is_system,
            permissions=as_codes(sort_permissions(perms[r.id])),
            users_count=counts.get(r.id, 0),
        )
        for r in roles
    ]
    return items, total


async def _ensure_role_name_free(
    session: AsyncSession, name: str, *, except_id: int | None
) -> None:
    taken = select(Role.id).where(func.lower(Role.name) == func.lower(name))
    if except_id is not None:
        taken = taken.where(Role.id != except_id)
    if await session.scalar(taken) is not None:
        await session.rollback()
        raise AppError("role_name_taken", f"Роль «{name}» уже существует", 409)


async def create_role(session: AsyncSession, body: RoleIn) -> RoleOut:
    await lock_staff_admin(session)
    await _ensure_role_name_free(session, body.name, except_id=None)
    role = Role(name=body.name, is_system=False)
    session.add(role)
    await session.flush()
    codes = sorted(set(body.permissions))
    if codes:
        await session.execute(
            insert(RolePermission), [{"role_id": role.id, "permission": c} for c in codes]
        )
    await session.commit()
    return await _role_out(session, role)


async def update_role(session: AsyncSession, role_id: int, body: RoleIn) -> RoleOut:
    await lock_staff_admin(session)
    role = await session.get(Role, role_id, populate_existing=True)
    if role is None:
        await session.rollback()
        raise _role_not_found()
    await _ensure_role_name_free(session, body.name, except_id=role_id)

    old = set(await role_permissions(session, role_id))
    new = {str(c) for c in body.permissions}
    role.name = body.name
    if old - new:
        await session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission.in_(old - new)
            )
        )
    if new - old:
        await session.execute(
            insert(RolePermission),
            [{"role_id": role_id, "permission": c} for c in sorted(new - old)],
        )
    await session.flush()
    if str(Permission.USERS_MANAGE) in old - new:
        await ensure_admin_remains(session)
    await session.commit()
    return await _role_out(session, role)


async def delete_role(session: AsyncSession, role_id: int) -> None:
    await lock_staff_admin(session)
    role = await session.get(Role, role_id, populate_existing=True)
    if role is None:
        await session.rollback()
        raise _role_not_found()
    users_count = (await _users_counts(session, [role_id])).get(role_id, 0)
    if users_count:
        await session.rollback()
        raise AppError("role_in_use", ROLE_IN_USE_MESSAGE, 409, {"users_count": users_count})
    # Роль без сотрудников не даёт никому права, поэтому инвариант администратора не страдает.
    # Права удаляются каскадом (FK ON DELETE CASCADE).
    await session.execute(delete(Role).where(Role.id == role_id))
    await session.commit()


# --------------------------------------------------------------------- сотрудники


def _user_not_found() -> AppError:
    return AppError("user_not_found", "Сотрудник не найден", 404)


def _login_taken(login: str) -> AppError:
    return AppError("login_taken", f"Логин «{login}» уже занят", 409)


def _user_out(user: StaffUser, role: Role) -> UserOut:
    return UserOut(
        id=user.id,
        full_name=user.full_name,
        login=user.login,
        role=RoleRef(id=role.id, name=role.name),
        is_blocked=user.is_blocked,
        created_at=user.created_at,
    )


async def _load_user(session: AsyncSession, user_id: int) -> tuple[StaffUser, Role]:
    row = (
        await session.execute(
            select(StaffUser, Role)
            .join(Role, Role.id == StaffUser.role_id)
            .where(StaffUser.id == user_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        await session.rollback()
        raise _user_not_found()
    user, role = row
    return user, role


async def list_users(session: AsyncSession, limit: int, offset: int) -> tuple[list[UserOut], int]:
    total = await session.scalar(select(func.count()).select_from(StaffUser)) or 0
    rows = await session.execute(
        select(StaffUser, Role)
        .join(Role, Role.id == StaffUser.role_id)
        .order_by(StaffUser.id)
        .limit(limit)
        .offset(offset)
    )
    return [_user_out(u, r) for u, r in rows], total


async def _require_role(session: AsyncSession, role_id: int) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        await session.rollback()
        raise _role_not_found()
    return role


async def create_user(session: AsyncSession, body: UserCreateIn) -> UserOut:
    await lock_staff_admin(session)
    role = await _require_role(session, body.role_id)
    if (
        await session.scalar(
            select(StaffUser.id).where(func.lower(StaffUser.login) == func.lower(body.login))
        )
        is not None
    ):
        await session.rollback()
        raise _login_taken(body.login)
    user = StaffUser(
        full_name=body.full_name,
        login=body.login,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        role_id=role.id,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _login_taken(body.login) from None
    return _user_out(user, role)


async def revoke_user_sessions(
    session: AsyncSession, user_id: int, *, keep_session_id: str | None = None
) -> None:
    stmt = update(StaffSession).where(
        StaffSession.user_id == user_id, StaffSession.revoked_at.is_(None)
    )
    if keep_session_id is not None:
        stmt = stmt.where(StaffSession.id != keep_session_id)
    await session.execute(stmt.values(revoked_at=utcnow()))


async def update_user(
    session: AsyncSession, user_id: int, body: UserUpdateIn, *, keep_session_id: str | None
) -> UserOut:
    await lock_staff_admin(session)
    user, role = await _load_user(session, user_id)
    role_changed = body.role_id is not None and body.role_id != user.role_id
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role_id is not None and role_changed:
        role = await _require_role(session, body.role_id)
        user.role_id = role.id
    if body.password is not None:
        user.password_hash = await asyncio.to_thread(hash_password, body.password)
        # Смена пароля завершает чужие сессии (свою, с которой правят, оставляем)
        await revoke_user_sessions(session, user_id, keep_session_id=keep_session_id)
    await session.flush()
    if role_changed:
        await ensure_admin_remains(session)
    await session.commit()
    return _user_out(user, role)


async def set_blocked(session: AsyncSession, user_id: int, *, blocked: bool) -> UserOut:
    await lock_staff_admin(session)
    user, role = await _load_user(session, user_id)
    if user.is_blocked != blocked:
        user.is_blocked = blocked
        if blocked:
            await revoke_user_sessions(session, user_id)
        await session.flush()
        if blocked:
            await ensure_admin_remains(session)
    await session.commit()
    return _user_out(user, role)
