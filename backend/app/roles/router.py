"""Роли, разрешения и учётные записи сотрудников (AD-03, AD-04)."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, Page, err
from app.api.deps import staff
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.db import get_session
from app.roles import service
from app.roles.schemas import (
    PermissionOut,
    RoleIn,
    RoleOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)

roles_router = APIRouter(prefix="/admin/roles", tags=["admin: roles"])
permissions_router = APIRouter(prefix="/admin/permissions", tags=["admin: roles"])
users_router = APIRouter(prefix="/admin/users", tags=["admin: users"])


@roles_router.get(
    "",
    operation_id="roles_list",
    summary="Список ролей",
    description="Разрешение: `users.manage`.",
    response_model=Page[RoleOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def roles_list(
    limit: Limit = 50, offset: Offset = 0, session: AsyncSession = Depends(get_session)
) -> Page[RoleOut]:
    items, total = await service.list_roles(session, limit, offset)
    return Page[RoleOut](items=items, total=total)


@roles_router.post(
    "",
    operation_id="roles_create",
    summary="Создать роль",
    description="Разрешение: `users.manage`. Название уникально без учёта регистра.",
    status_code=201,
    response_model=RoleOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, (409, "`role_name_taken`: роль с таким названием уже есть"), 422),
)
async def roles_create(body: RoleIn, session: AsyncSession = Depends(get_session)) -> RoleOut:
    return await service.create_role(session, body)


@roles_router.put(
    "/{role_id}",
    operation_id="roles_update",
    summary="Изменить роль",
    description=(
        "Разрешение: `users.manage`. Изменение прав действует для сотрудников со следующего "
        "входа (AD-04). Нельзя сохранить изменения, после которых ни у одной действующей "
        "учётной записи не останется разрешения `users.manage` (`last_admin_permission`)."
    ),
    response_model=RoleOut,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        (404, "`role_not_found`: роли нет"),
        422,
        (
            409,
            "`last_admin_permission`: не останется администратора; "
            "`role_name_taken`: название занято",
        ),
    ),
)
async def roles_update(
    role_id: int, body: RoleIn, session: AsyncSession = Depends(get_session)
) -> RoleOut:
    return await service.update_role(session, role_id, body)


@roles_router.delete(
    "/{role_id}",
    operation_id="roles_delete",
    summary="Удалить роль",
    description=(
        "Разрешение: `users.manage`. Роль, назначенная хотя бы одному сотруднику, удалению "
        "не подлежит: `409 role_in_use` (`details.users_count`)."
    ),
    status_code=204,
    response_class=Response,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        (404, "`role_not_found`: роли нет"),
        (409, "`role_in_use`: роль назначена сотрудникам"),
    ),
)
async def roles_delete(role_id: int, session: AsyncSession = Depends(get_session)) -> None:
    await service.delete_role(session, role_id)


@permissions_router.get(
    "",
    operation_id="permissions_list",
    summary="Справочник разрешений",
    description="Разрешение: `users.manage`. Каталог разрешений зашит в коде (AD-04).",
    response_model=list[PermissionOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def permissions_list() -> list[PermissionOut]:
    return service.permissions_catalog()


@users_router.get(
    "",
    operation_id="users_list",
    summary="Список сотрудников",
    description="Разрешение: `users.manage`.",
    response_model=Page[UserOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def users_list(
    limit: Limit = 50, offset: Offset = 0, session: AsyncSession = Depends(get_session)
) -> Page[UserOut]:
    items, total = await service.list_users(session, limit, offset)
    return Page[UserOut](items=items, total=total)


@users_router.post(
    "",
    operation_id="users_create",
    summary="Создать сотрудника",
    description=(
        "Разрешение: `users.manage`. ФИО, логин, пароль (не короче 8 символов) и роль. "
        "Логин уникален без учёта регистра."
    ),
    status_code=201,
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        (404, "`role_not_found`: такой роли нет"),
        422,
        (409, "`login_taken`: логин уже занят"),
    ),
)
async def users_create(body: UserCreateIn, session: AsyncSession = Depends(get_session)) -> UserOut:
    return await service.create_user(session, body)


@users_router.put(
    "/{user_id}",
    operation_id="users_update",
    summary="Изменить сотрудника",
    description=(
        "Разрешение: `users.manage`. Можно сменить ФИО, роль и пароль (все поля необязательны). "
        "Новая роль и права действуют со следующего входа сотрудника. Смена пароля завершает "
        "остальные сессии сотрудника. Нельзя сменить роль так, чтобы не осталось действующей "
        "учётной записи с `users.manage` (`last_admin_permission`)."
    ),
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        (404, "`user_not_found` или `role_not_found`"),
        422,
        (409, "`last_admin_permission`: не останется администратора"),
    ),
)
async def users_update(
    user_id: int,
    body: UserUpdateIn,
    current: CurrentStaff = Depends(get_current_staff),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    return await service.update_user(session, user_id, body, keep_session_id=current.session_id)


@users_router.post(
    "/{user_id}/block",
    operation_id="users_block",
    summary="Заблокировать сотрудника",
    description=(
        "Разрешение: `users.manage`. Действующие сессии сотрудника отзываются, войти он не "
        "сможет. Нельзя заблокировать последнюю действующую учётную запись с `users.manage` "
        "(`last_admin_permission`)."
    ),
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        (404, "`user_not_found`: сотрудника нет"),
        (409, "`last_admin_permission`: не останется администратора"),
    ),
)
async def users_block(user_id: int, session: AsyncSession = Depends(get_session)) -> UserOut:
    return await service.set_blocked(session, user_id, blocked=True)


@users_router.post(
    "/{user_id}/unblock",
    operation_id="users_unblock",
    summary="Разблокировать сотрудника",
    description="Разрешение: `users.manage`.",
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, (404, "`user_not_found`: сотрудника нет")),
)
async def users_unblock(user_id: int, session: AsyncSession = Depends(get_session)) -> UserOut:
    return await service.set_blocked(session, user_id, blocked=False)


router = APIRouter()
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(users_router)
